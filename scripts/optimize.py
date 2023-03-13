from autotune.utils.config import parse_args
from autotune.database.mysqldb import MysqlDB
from autotune.database.postgresqldb import PostgresqlDB
from autotune.dbenv import DBEnv
from autotune.tuner import DBTuner
import argparse
import subprocess as sp

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=[], help='config file', action='append')
    opt = parser.parse_args()

    print(opt.config)
    numitr = 5

    for itr in range(numitr):
        for config_file in opt.config:
            # sp.run('/usr/lib/postgresql/14/bin/pg_ctl -D /mnt/nvme0n1/peijingx/pg_datadir stop',shell=True)
            # sp.run('cp /mnt/nvme0n1/peijingx/pg_datadir/postgresql.conf.old /mnt/nvme0n1/peijingx/pg_datadir/postgresql.conf', shell = True)
            # sp.run('/usr/lib/postgresql/14/bin/pg_ctl -D /mnt/nvme0n1/peijingx/pg_datadir start',shell=True)
            # sp.run('pg_restore -h /home/peijingx/pg_socks -p 5469 -d peijingx_tpcc100_knobs -j 64 -c --if-exists /mnt/nvme0n1/tpcc_100', shell = True)

            args_db, args_tune = parse_args(config_file)
            old_id = args_tune['task_id']
            if args_db['db'] == 'postgresql':
                db = PostgresqlDB(args_db)
            else:
                raise Exception("postgres only!")
            args_tune['task_id'] = f'{old_id}_{itr}'
            env = DBEnv(args_db, args_tune, db)
            tuner = DBTuner(args_db, args_tune, env)
            tuner.tune()

