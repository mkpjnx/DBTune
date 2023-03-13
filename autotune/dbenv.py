import os
import pdb
import time
import subprocess
import numpy as np
from multiprocessing import Manager
from multiprocessing.connection import Client
import sys
from .knobs import logger
from .utils.parser import parse_sysbench, parse_oltpbench, parse_job
from .knobs import initialize_knobs, get_default_knobs
import psutil
import multiprocessing as mp
from .resource_monitor import ResourceMonitor
from autotune.workload import SYSBENCH_WORKLOAD, JOB_WORKLOAD, OLTPBENCH_WORKLOADS
from autotune.utils.constants import MAXINT, SUCCESS, FAILED, TIMEOUT
from autotune.utils.parser import is_number


class DBEnv:
    def __init__(self, args, args_tune, db):
        self.db = db
        self.args = args
        self.workload = self.get_workload()
        self.log_path = "./log"
        self.num_metrics = self.db.num_metrics
        self.threads = int(args['thread_num'])
        self.best_result = './autotune_best.res'
        self.knobs_detail = initialize_knobs(args['knob_config_file'], int(args['knob_num']))
        self.default_knobs = get_default_knobs()
        self.online_mode = eval(args['online_mode'])
        self.remote_mode = eval(args['remote_mode'])
        self.oltpbench_config_xml = args['oltpbench_config_xml']
        self.step_count = 0
        self.connect_sucess = True
        self.reinit_interval = 0
        self.reinit = False
        if self.reinit_interval:
            self.reinit = False
        self.generate_time()
        self.y_variable = eval(args_tune['performance_metric'])
        self.reference_point = self.generate_reference_point(eval(args_tune['reference_point']))

        if args_tune['constraints'] is None or args_tune['constraints'] == '':
            self.constraints = []
        else:
            self.constraints = eval(args_tune['constraints'])
        self.lhs_log = args['lhs_log']
        self.cpu_core = args['cpu_core']
        self.info =  {
            'objs': self.y_variable,
            'constraints': self.constraints
        }

    def generate_reference_point(self, user_defined_reference_point):
        if len(self.y_variable) <= 1:
            return None

        reference_point_dir = {
            'tps': 0,
            'lat': BENCHMARK_RUNNING_TIME,
            'qps': 0,
            'cpu': 0,
            'readIO': 0,
            'writeIO': 0,
            'virtualMem': 0,
            'physical': 0,
        }
        reference_point = []
        for key in self.y_variable:
            use_defined_value = user_defined_reference_point[self.y_variable.index(key)]
            if is_number(use_defined_value):
                reference_point.append(use_defined_value)
            else:
                key = key.strip().strip('-')
                reference_point.append(reference_point_dir[key])

        return reference_point

    def get_workload(self):
        if self.args['workload'].startswith('oltpbench_'):
            wl = dict(OLTPBENCH_WORKLOADS)
        else:
            raise ValueError('Invalid workload!')
        return wl

    def generate_time(self):
        global BENCHMARK_RUNNING_TIME
        global BENCHMARK_WARMING_TIME
        global TIMEOUT_TIME
        global RESTART_FREQUENCY

        # if self.workload['name'] == 'sysbench' or self.workload['name'] == 'oltpbench':
        if self.workload['name'] == 'oltpbench':
            try:
                BENCHMARK_RUNNING_TIME = int(self.args['workload_time'])
            except:
                BENCHMARK_RUNNING_TIME = 120
            try:
                BENCHMARK_WARMING_TIME = int(self.args['workload_warmup_time'])
            except:
                BENCHMARK_WARMING_TIME = 30
            TIMEOUT_TIME = BENCHMARK_RUNNING_TIME + BENCHMARK_WARMING_TIME + 30
            RESTART_FREQUENCY = 200

        # elif self.workload['name'] == 'job':
        #     try:
        #         BENCHMARK_RUNNING_TIME = int(self.args['workload_time'])
        #     except:
        #         BENCHMARK_RUNNING_TIME = 240
        #     try:
        #         BENCHMARK_WARMING_TIME = int(self.args['workload_warmup_time'])
        #     except:
        #         BENCHMARK_WARMING_TIME = 0
        #     TIMEOUT_TIME = BENCHMARK_RUNNING_TIME + BENCHMARK_WARMING_TIME
        #     RESTART_FREQUENCY = 30000

        else:
            raise ValueError('Invalid workload nmae!')

    def get_external_metrics(self, filename=''):
        print("EXTERN")
        if not os.path.exists(filename):
            print("benchmark result file does not exist!")
            return[-1, -1, -1, -1, -1, -1]
        if self.workload['name'] == 'oltpbench':
            result = parse_oltpbench(filename)
            print(f"BENCH RESULT {result}")
            return result
        else:
            raise ValueError('Invalid workload name!')
        

    def get_benchmark_cmd(self):
        timestamp = int(time.time())
        filename = self.log_path + '/{}.log'.format(timestamp)
        dirname, _ = os.path.split(os.path.abspath(__file__))

        if self.workload['name'] == 'oltpbench':
            cmd = self.workload['cmd'].format(dirname + '/cli/run_oltpbench.sh',
                                              self.args['oltpbench_type'],
                                              self.oltpbench_config_xml,
                                              filename)
        else:
            raise ValueError('Invalid workload name!')

        logger.info('[DBG]. {}'.format(cmd))
        return cmd, filename

    def get_states(self, collect_resource=0):
        # start Internal Metrics Collection
        internal_metrics = Manager().list()
        im = mp.Process(target=self.db.get_internal_metrics,
                        args=(internal_metrics, BENCHMARK_RUNNING_TIME, BENCHMARK_WARMING_TIME))
        self.db.set_im_alive(True)
        im.start()

        # start Resource Monition (if activated)
        if collect_resource:
            if self.remote_mode:
                # start remote Resource Monitor
                clientDB_address = (self.db.host, 6001)
                clientDB_conn = Client(clientDB_address, authkey=b'DBTuner')
                clientDB_conn.send(self.db.pid)
            else:
                rm = ResourceMonitor(self.db.pid, 1, BENCHMARK_WARMING_TIME, BENCHMARK_RUNNING_TIME)
                rm.run()

        # start Benchmark
        benchmark_timeout = False
        cmd, filename = self.get_benchmark_cmd()
        print("[{}] benchmark start!".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
        p_benchmark = subprocess.Popen(cmd, shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE,
                                       close_fds=True)
        try:
            outs, errs = p_benchmark.communicate(timeout=TIMEOUT_TIME)
            # print(str(outs), flush=True)
            # print(str(errs), flush=True)
            ret_code = p_benchmark.poll()
            if ret_code == 0:
                print("[{}] benchmark finished!".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
            else:
                print("run benchmark get error {}".format(ret_code))
        except subprocess.TimeoutExpired:
            benchmark_timeout = True
            print("[{}] benchmark timeout!".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))

        # terminate Benchmark
        if not self.remote_mode:
            subprocess.Popen(self.db.clear_cmd, shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE,
                             close_fds=True)
            print("[{}] clear processlist".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))

        # stop Internal Metrics Collection
        self.db.set_im_alive(False)
        im.join()

        # stop Resource Monition (if activated)
        if collect_resource:
            if self.remote_mode:
                # send Benchmark-Finish msg to remote Resource Monitor Process
                clientDB_conn.send('benchmark_finished')
                # receive remote Monitor Data
                monitor_data = clientDB_conn.recv()
                cpu, avg_read_io, avg_write_io, avg_virtual_memory, avg_physical_memory = monitor_data
                # close connection
                clientDB_conn.close()

            else:
                rm.terminate()
                cpu, avg_read_io, avg_write_io, avg_virtual_memory, avg_physical_memory = rm.get_monitor_data_avg()
        else:
            cpu, avg_read_io, avg_write_io, avg_virtual_memory, avg_physical_memory = 0, 0, 0, 0, 0


        external_metrics = self.get_external_metrics(filename)
        internal_metrics, dirty_pages, hit_ratio, page_data = self.db._post_handle(internal_metrics)
        logger.info('internal metrics: {}.'.format(list(internal_metrics)))

        return benchmark_timeout, external_metrics, internal_metrics, (
            cpu, avg_read_io, avg_write_io, avg_virtual_memory, avg_physical_memory, dirty_pages, hit_ratio, page_data)

    def step_GP(self, knobs, collect_resource=True):
        # return False, np.random.rand(6), np.random.rand(65), np.random.rand(8)

        # re-init database if activated
        if self.reinit_interval > 0 and self.reinit_interval % RESTART_FREQUENCY == 0:
            if self.reinit:
                logger.info('reinitializing db begin')
                self.db.reinitdb_magic(self.remote_mode)
                logger.info('db reinitialized')
        self.step_count = self.step_count + 1
        self.reinit_interval = self.reinit_interval + 1

        # modify and apply knobs
        for key in knobs.keys():
            value = knobs[key]
            if not key in self.knobs_detail.keys() or not self.knobs_detail[key]['type'] == 'integer':
                continue
            if value > self.knobs_detail[key]['max']:
                knobs[key] = self.knobs_detail[key]['max']
                logger.info("{} with value of is larger than max, adjusted".format(key))
            elif value < self.knobs_detail[key]['min']:
                knobs[key] = self.knobs_detail[key]['min']
                logger.info("{} with value of is smaller than min, adjusted".format(key))

        logger.info("[step {}] generate knobs: {}".format(self.step_count, knobs))

        if self.online_mode:
            flag = self.db.apply_knobs_online(knobs)
        else:
            print("APPLY OFFLINE", flush = True)
            flag = self.db.apply_knobs_offline(knobs)

        if not flag:
            if self.reinit:
                logger.info('reinitializing db begin')
                self.db.reinitdb_magic(self.remote_mode)
                logger.info('db reinitialized')

            raise Exception('Apply knobs failed!')

        print("CALLING GETSTATE", flush = True)
        s = None
        try:
            s = self.get_states(collect_resource=collect_resource)
        except Exception as e:
            print(f"EXCEPTION getstate {e}", flush = True)
            raise e

        if s is None:
            if self.reinit:
                logger.info('reinitializing db begin')
                self.db.reinitdb_magic(self.remote_mode)
                logger.info('db reinitialized')

            raise Exception('Get states failed!')

        timeout, external_metrics, internal_metrics, resource = s

        format_str = '{}|tps_{}|lat_{}|qps_{}|tpsVar_{}|latVar_{}|qpsVar_{}|cpu_{}|readIO_{}|writeIO_{}|virtaulMem_{}|physical_{}|dirty_{}|hit_{}|data_{}|{}|65d\n'
        res = format_str.format(knobs, str(external_metrics[0]), str(external_metrics[1]), str(external_metrics[2]),
                                external_metrics[3], external_metrics[4],
                                external_metrics[5],
                                resource[0], resource[1], resource[2], resource[3], resource[4],
                                resource[5], resource[6], resource[7], list(internal_metrics))

        return timeout, external_metrics, internal_metrics, resource

    def get_objs(self, res):
        objs = []
        for y_variable in self.y_variable:
            key = y_variable.strip().strip('-')
            value = res[key]
            if not y_variable.strip()[0] == '-':
                value = - value
            objs.append(value)

        return objs

    def get_constraints(self, res):
        if len(self.constraints) == 0:
            return None

        locals().update(res)
        constraintL = []
        for constraint in self.constraints:
            value = eval(constraint)
            constraintL.append(value)

        return constraintL

    def step(self, config):

        knobs = config.get_dictionary().copy()
        for k in knobs.keys():
            if self.knobs_detail[k]['type'] == 'integer' and self.knobs_detail[k]['max'] > sys.maxsize:
                knobs[k] = knobs[k] * 1000

        try:
            timeout, metrics, internal_metrics, resource = self.step_GP(knobs, collect_resource=True)

            if timeout:
                trial_state = TIMEOUT
            else:
                trial_state = SUCCESS

            external_metrics = {
                'tps': metrics[0],
                'lat': metrics[1],
                'qps': metrics[2],
                'tpsVar': metrics[3],
                'latVar': metrics[4],
                'qpsVar': metrics[5],
            }

            resource = {
                'cpu': resource[0],
                'readIO': resource[1],
                'writeIO': resource[2],
                'IO': resource[1] + resource[2],
                'virtualMem': resource[3],
                'physical': resource[4],
                'dirty': resource[5],
                'hit': resource[6],
                'data': resource[7],
            }

            res = dict(external_metrics, **resource)
            objs = self.get_objs(res)
            constraints = self.get_constraints(res)
            return objs, constraints, external_metrics, resource, list(internal_metrics), self.info, trial_state

        except:
            return None, None, {}, {}, [], self.info, FAILED
