#Python-related imports
import math
import sys
from datetime import datetime
import os.path

#Torch imports
import torch
import torch.distributions as D
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Function

#PyData imports
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

#Module imports
from training import *
from plotting import *

#PyTorch settings
if torch.cuda.is_available():
    print('CUDA device detected.')
    active_device = torch.device('cuda')
else:
    #active_device = torch.device('cpu')
    print('No CUDA device detected.')
    raise EnvironmentError

torch.set_printoptions(precision = 8)
torch.manual_seed(0)
torch.cuda.manual_seed(0)
torch.cuda.manual_seed_all(0)
np.random.seed(0)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False

#IAF SSM time parameters
dt_flow = 1.0 #Increased from 0.1 to reduce memory.
t = 1000 #In hours.
n = int(t / dt_flow) + 1
t_span = np.linspace(0, t, n)
t_span_tensor = torch.reshape(torch.Tensor(t_span), [1, n, 1]).to(active_device) #T_span needs to be converted to tensor object. Additionally, facilitates conversion of I_S and I_D to tensor objects.

#SBM temperature forcing parameters
temp_ref = 283
temp_rise = 5 #High estimate of 5 celsius temperature rise by 2100.

#Training parameters
elbo_iter = 45000
elbo_lr = 1e-2
elbo_lr_decay = 0.6
elbo_lr_decay_step_size = 10000
elbo_warmup_iter = 5000
elbo_warmup_lr = 1e-6
ptrain_iter = 0
ptrain_alg = 'L1'
batch_size = 50
eval_batch_size = 100
final_eval_batch_size = 1000
x0_error_scale = 0.1
obs_error_scale = 0.05
prior_scale_factor = 0.25
num_layers = 5
reverse = True
base_state = False

train_args = {'t': t, 'dt_flow': dt_flow, 'elbo_iter': elbo_iter, 'elbo_lr': elbo_lr, 'elbo_lr_decay': elbo_lr_decay, 'elbo_lr_decay_step_size': elbo_lr_decay_step_size, 'elbo_warmup_iter': elbo_warmup_iter, 'elbo_warmup_lr': elbo_warmup_lr, 'ptrain_iter': ptrain_iter, 'ptrain_alg': ptrain_alg,
    'batch_size': batch_size, 'x0_error_scale': x0_error_scale, 'obs_error_scale': obs_error_scale, 'prior_scale_factor': prior_scale_factor, 'num_layers': num_layers, 'reverse': reverse, 'base_state': base_state}

#Specify desired SBM SDE model type and details.
state_dim_SCON = 3
SBM_SDE_class = 'SCON'
diffusion_type = 'C'
learn_CO2 = True
theta_dist = 'RescaledLogitNormal' #String needs to be exact name of the distribution class. Options are 'TruncatedNormal' and 'RescaledLogitNormal'.
theta_post_dist = 'MultivariateLogitNormal'
fix_theta_dict = None

#Load parameterization of priors.
SCON_C_priors_details = {k: v.to(active_device) for k, v in torch.load(os.path.join('generated_data/SCON-C_CO2_logit_short/', 'p_theta.pt')).items()}

#Initial condition prior means
x0_SCON_tensor = torch.load(os.path.join('generated_data/SCON-C_CO2_logit_short/', 'p_x0.pt')).to(active_device)
x0_prior_SCON = D.multivariate_normal.MultivariateNormal(x0_SCON_tensor, scale_tril = torch.eye(state_dim_SCON).to(active_device) * x0_error_scale * x0_SCON_tensor)

#Generate exogenous input vectors.
#Obtain temperature forcing function.
temp_tensor = temp_gen(t_span_tensor, temp_ref, temp_rise).to(active_device)

#Obtain SOC and DOC pool litter input vectors for use in flow SDE functions.
i_s_tensor = i_s(t_span_tensor).to(active_device) #Exogenous SOC input function
i_d_tensor = i_d(t_span_tensor).to(active_device) #Exogenous DOC input function

#Assign path to observations .csv file.
csv_data_path = os.path.join('generated_data/SCON-C_CO2_logit_short/', 'data.csv')

#Call training loop function.
net, q_theta, p_theta, obs_model, norm_hist, ELBO_hist, SBM_SDE_instance = train(
        active_device, elbo_lr, elbo_iter, batch_size,
        csv_data_path, obs_error_scale, t, dt_flow, n, 
        t_span_tensor, i_s_tensor, i_d_tensor, temp_tensor, temp_ref,
        SBM_SDE_class, diffusion_type, x0_prior_SCON,
        SCON_C_priors_details, fix_theta_dict, learn_CO2, theta_dist, 
        THETA_POST_DIST = theta_post_dist, EVAL_BATCH_SIZE = eval_batch_size, EVAL_ELBO_EVERY = 100,
        ELBO_WARMUP_ITER = elbo_warmup_iter, ELBO_WARMUP_INIT_LR = elbo_warmup_lr, ELBO_LR_DECAY = elbo_lr_decay, ELBO_LR_DECAY_STEP_SIZE = elbo_lr_decay_step_size,
        PRINT_EVERY = 20, VERBOSE = True,
        DEBUG_SAVE_DIR = None, PTRAIN_ITER = ptrain_iter, PTRAIN_ALG = ptrain_alg,
        NUM_LAYERS = num_layers, REVERSE = reverse, BASE_STATE = base_state)
print('Training finished. Moving to saving of output files.')

#Save net and ELBO files.
now = datetime.now()
now_string = 'SCON-C_CO2_logit_short' + now.strftime('_%Y_%m_%d_%H_%M_%S')
save_string = f'_iter_{elbo_iter}_warmup_{elbo_warmup_iter}_t_{t}_dt_{dt_flow}_batch_{batch_size}_layers_{num_layers}_lr_{elbo_lr}_decay_step_{elbo_lr_decay_step_size}_warmup_lr_{elbo_warmup_lr}_sd_scale_{prior_scale_factor}_{now_string}.pt'
outputs_folder = 'training_pt_outputs/'
if not os.path.exists(outputs_folder):
    os.makedirs(outputs_folder)

train_args_save_string = os.path.join(outputs_folder, 'train_args' + save_string)
net_save_string = os.path.join(outputs_folder, 'net' + save_string)
net_state_dict_save_string = os.path.join(outputs_folder,'net_state_dict' + save_string)
q_theta_save_string = os.path.join(outputs_folder, 'q_theta' + save_string)
q_theta_state_dict_save_string = os.path.join(outputs_folder, 'q_theta_state_dict' + save_string)
p_theta_save_string = os.path.join(outputs_folder, 'p_theta' + save_string)
obs_model_save_string = os.path.join(outputs_folder, 'obs_model' + save_string)
ELBO_save_string = os.path.join(outputs_folder, 'ELBO' + save_string)
SBM_SDE_instance_save_string = os.path.join(outputs_folder, 'SBM_SDE_instance' + save_string)

torch.save(train_args, train_args_save_string)
torch.save(net, net_save_string)
torch.save(net.state_dict(), net_state_dict_save_string) #For loading net on CPU.
torch.save(q_theta, q_theta_save_string)
torch.save(q_theta.state_dict(), q_theta_state_dict_save_string)
torch.save(p_theta, p_theta_save_string)
torch.save(obs_model, obs_model_save_string)
torch.save(ELBO_hist, ELBO_save_string)
torch.save(SBM_SDE_instance, SBM_SDE_instance_save_string)
print('Output files saving finished.') # Moving to plotting.

#Evaluate test ELBO and sample x
neg_ELBO, x_add_CO2 = eval_elbo(final_eval_batch_size, net, q_theta, p_theta, obs_model, fix_theta_dict, dt_flow, n, SBM_SDE_instance, x0_prior_SCON, learn_CO2)
x_eval_save_string = os.path.join(outputs_folder, 'x_eval' + save_string)
torch.save((neg_ELBO, x_add_CO2), x_eval_save_string)

#Plot training posterior results and ELBO history.
#plots_folder = 'training_plots/'
#if not os.path.exists(plots_folder):
#    os.makedirs(plots_folder)
#plot_elbo(ELBO_hist, elbo_iter, elbo_warmup_iter, t, dt_flow, batch_size, eval_batch_size, num_layers, elbo_lr, elbo_lr_decay_step_size, elbo_warmup_lr, prior_scale_factor, plots_folder, now_string, xmin = elbo_warmup_iter + int(elbo_iter / 2))
#print('ELBO plotting finished.')
#plot_states_post(x_add_CO2, q_theta, obs_model, SBM_SDE_instance, elbo_iter, elbo_warmup_iter, t, dt_flow, batch_size, eval_batch_size, num_layers, elbo_lr, elbo_lr_decay_step_size, elbo_warmup_lr, prior_scale_factor, plots_folder, now_string, fix_theta_dict, learn_CO2, ymin_list = [0, 0, 0, 0], ymax_list = [70., 5., 8., 0.03])
#print('States fit plotting finished.')
#true_theta = torch.load(os.path.join('generated_data/SCON-C_CO2_logit_short/', 'theta.pt'), map_location = active_device)
#plot_theta(p_theta, q_theta, true_theta, elbo_iter, elbo_warmup_iter, t, dt_flow, batch_size, eval_batch_size, num_layers, elbo_lr, elbo_lr_decay_step_size, elbo_warmup_lr, prior_scale_factor, plots_folder, now_string)
#print('Prior-posterior pair plotting finished.')
