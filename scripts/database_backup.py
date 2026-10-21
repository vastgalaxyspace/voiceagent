"""Operator-only pg_dump archives and restore drills through libpq service files.

Credentials stay in .pgpass / pg_service.conf, never command-line URLs. Use a
pg_dump version at least as new as the source server. Store dumps off-host and
encrypted; this script neither schedules, encrypts nor uploads them.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4


def run(command, service=None):
    environment = os.environ.copy()
    if service:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', service):
            raise ValueError('Use a simple libpq service name, not a connection URL')
        # A service supplies connection fields. Do not let ambient overrides
        # silently redirect a restore to another database.
        for key in ('PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD', 'PGSERVICE'):
            environment.pop(key, None)
        environment['PGSERVICE'] = service
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=1800)
    if result.returncode:
        raise RuntimeError('PostgreSQL operation failed; check service configuration, permissions and database state')
    return result.stdout


def verify(archive):
    archive = Path(archive).resolve(strict=True)
    if not archive.is_file() or archive.stat().st_size == 0:
        raise ValueError('Provide a nonempty archive file')
    run(['pg_restore', '--list', str(archive)])
    return archive


def backup(service, directory):
    directory = Path(directory).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError('Provide an existing private backup directory')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive = directory / f'voiceagent-{stamp}-{uuid4().hex[:8]}.dump'
    # Reserve a unique path, with restrictive permissions on POSIX hosts.
    descriptor = os.open(archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        run(['pg_dump', '--no-password', '--format=custom', '--no-owner', '--no-acl',
             '--file', str(archive)], service)
        return verify(archive)
    except BaseException:
        archive.unlink(missing_ok=True)  # Only our newly reserved output file.
        raise


def restore(service, archive):
    archive = verify(archive)
    tables = run(['psql', '-X', '--no-password', '--set=ON_ERROR_STOP=1', '--tuples-only', '--no-align',
                  '--command', "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                  "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' "
                  "AND c.relkind IN ('r','p','v','m','S','f');"], service)
    if tables.strip() != '0':
        raise ValueError('Restore target must be an empty disposable database')
    run(['pg_restore', '--no-password', '--dbname', f'service={service}', '--no-owner', '--no-acl',
         '--exit-on-error', '--single-transaction', str(archive)], service)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    create = commands.add_parser('backup')
    create.add_argument('--service', required=True)
    create.add_argument('--directory', type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('--archive', type=Path, required=True)
    drill = commands.add_parser('restore')
    drill.add_argument('--service', required=True)
    drill.add_argument('--archive', type=Path, required=True)
    drill.add_argument('--confirm-empty-target', action='store_true', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'backup':
            print(backup(args.service, args.directory))
        elif args.action == 'verify':
            verify(args.archive)
            print('Archive table of contents is readable; a restore drill is still required.')
        else:
            restore(args.service, args.archive)
            print('Restore completed. Apply runtime grants and validate the restored application separately.')
    except Exception:
        raise SystemExit('Database operation failed; check tools, service settings, permissions and the target database') from None


if __name__ == '__main__':
    main()
