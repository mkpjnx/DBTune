import os
import sys
from autotune.utils.config_space import ConfigurationSpace, UniformIntegerHyperparameter, UniformFloatHyperparameter
from autotune.utils.config_space import CategoricalHyperparameter, OrdinalHyperparameter
from autotune.workload_map import WorkloadMapping
from autotune.pipleline.pipleline import PipleLine
from .knobs import ts, logger
from .utils.parser import  get_hist_json
from autotune.utils.history_container import HistoryContainer
import pdb

class DBTuner:
    def __init__(self, args_db, args_tune, env):
        self.env = env
        self.create_output_folders()
        self.args_tune = args_tune
        self.method = args_tune['optimize_method']
        self.y_variable = env.y_variable
        self.transfer_framework = args_tune['transfer_framework']
        self.hc_path = self.args_tune['data_repo']

        self.hcL = []
        self.model_params_path = ''
        self.surrogate_type = None
        self.config_space = ConfigurationSpace()
        self.objs = eval(args_tune['performance_metric'])
        if args_tune['constraints'] is None or args_tune['constraints'] == '':
            self.constraints = []
        else:
            self.constraints = eval(args_tune['constraints'])
        self.setup_configuration_space()
        self.setup_transfer()


    def setup_configuration_space(self):
        KNOBS = self.env.knobs_detail
        knobs_list = []

        for name in KNOBS.keys():
            value = KNOBS[name]
            knob_type = value['type']
            if knob_type == 'enum':
                knob = CategoricalHyperparameter(name, [str(i) for i in value["enum_values"]])
            elif knob_type == 'integer':
                min_val, max_val, default = value['min'], value['max'], value['default']
                if self.env.knobs_detail[name]['max'] > sys.maxsize:
                    min_val, max_val, default = int(min_val / 1000), int(max_val / 1000), int(default / 1000)
                knob = UniformIntegerHyperparameter(name, min_val, max_val, default_value=default)
            elif knob_type == 'float':
                min_val, max_val, default = value['min'], value['max'], value['default']
                knob = UniformFloatHyperparameter(name, min_val, max_val, default_value=default)
            elif knob_type == 'ordinal':
                knob = OrdinalHyperparameter(name, value["ordered_values"])
            else:
                raise ValueError(f'Invalid knob type! {name}:{knob_type}')

            knobs_list.append(knob)

        self.config_space.add_hyperparameters(knobs_list)

    def setup_transfer(self):
        if self.transfer_framework == 'none':
            if self.method == 'SMAC':
                self.surrogate_type = 'prf'
            elif self.method == 'MBO':
                self.surrogate_type = 'gp'
            elif self.method == 'auto':
                self.surrogate_type = 'auto'

        elif self.transfer_framework in ['workload_map', 'rgpe']:
            files = os.listdir(self.hc_path)
            for f in files:
                try:
                    task_id = f.split('.')[0].split('_')[-1]
                    fn = os.path.join(self.hc_path, f)
                    history_container = HistoryContainer(task_id, config_space=self.config_space)
                    history_container.load_history_from_json(fn)
                    self.hcL.append(history_container)
                except:
                    logger.info('load history failed for {}'.format(f))

            if self.method == 'SMAC':
                method = 'prf'
            elif self.method == 'MBO':
                method = 'gp'
            else:
                raise ValueError('Invalid method for %s!' % self.transfer_framework)

            if self.transfer_framework == 'rgpe':
                self.surrogate_type = 'tlbo_rgpe_' + method
            else:
                self.surrogate_type = 'tlbo_mapping_' + method

        elif self.transfer_framework == 'finetune':
            if self.method != 'DDPG':
                raise ValueError('Invalid method for finetune!')

            self.model_params_path = self.args_tune['params']

        elif   self.transfer_framework == 'context':
            self.surrogate_type = 'context_prf'
            if self.method != 'SMAC':
                raise ValueError('We currently only support SMAC. Invalid method for context!')

        else:
            raise ValueError('Invalid string %s for transfer framework!' % self.transfer_framework)


    def tune(self):
        bo = PipleLine(self.env.step,
                       self.config_space,
                       num_objs=len(self.objs),
                       num_constraints=len(self.constraints),
                       optimizer_type=self.method,
                       max_runs=int(self.args_tune['max_runs']),
                       surrogate_type=self.surrogate_type,
                       history_bo_data=self.hcL,
                       acq_optimizer_type='local_random',  # 'random_scipy',#
                       selector_type=self.args_tune['selector_type'],
                       initial_runs=int(self.args_tune['initial_runs']),
                       incremental=self.args_tune['incremental'],
                       incremental_every=int(self.args_tune['incremental_every']),
                       incremental_num=int(self.args_tune['incremental_num']),
                       init_strategy='random_explore_first',
                       ref_point= self.env.reference_point,
                       task_id=self.args_tune['task_id'],
                       time_limit_per_trial=60 * 200,
                       num_hps_init=int(self.args_tune['initial_tunable_knob_num']),
                       num_metrics=self.env.db.num_metrics,
                       mean_var_file=self.args_tune['mean_var_file'],
                       batch_size=int(self.args_tune['batch_size']),
                       params=self.model_params_path,
                       )

        history = bo.run()
        if history.num_objs == 1:
            import matplotlib.pyplot as plt
            history.plot_convergence()
            plt.savefig('%s.png' % history.task_id)


    @staticmethod
    def create_output_folders():
        output_folders = ['log', ]
        for folder in output_folders:
            if not os.path.exists(folder):
                os.mkdir(folder)

