import numpy as np
import torch
import torch.nn as nn
import torch.optim as opt
from torch.autograd import Variable
import gym

from jigglypuffRL.common import (
    get_policy_from_name,
    get_value_from_name,
    save_params,
    load_params,
)


class VPG:
    """
    Vanilla Policy Gradient algorithm
    Paper: https://papers.nips.cc/paper/1713-policy-gradient-methods-for-reinforcement-learning-with-function-approximation.pdf
    :param policy: (str) The policy model to use (MlpPolicy)
    :param value: (str) The value function model to use (MlpValue)
    :param env: (Gym environment) The environment to learn from
    :param timesteps_per_actorbatch: (int) timesteps per actor per update
    :param gamma: (float) discount factor
    :param clip_param: (float) clipping parameter epsilon
    :param actor_batchsize: (int) trajectories per optimizer epoch
    :param epochs: (int) the optimizer's number of epochs
    :param lr_policy: (float) policy network learning rate
    :param lr_value: (float) value network learning rate
    :param policy_copy_interval: (int) number of optimizer before copying params from new policy to old policy
    :param save_interval: (int) Number of episodes between saves of models
    :param tensorboard_log: (str) the log location for tensorboard (if None, no logging)
    :param seed (int): seed for torch and gym
    :param device (str): device to use for tensor operations; 'cpu' for cpu and 'cuda' for gpu
    :param pretrained: (boolean) if model has already been trained
    :param save_name: (str) model save name (if None, model hasn't been pretrained)
    :param save_version: (int) model save version (if None, model hasn't been pretrained)
    """

    def __init__(
        self,
        policy,
        value,
        env,
        timesteps_per_actorbatch=200,
        gamma=0.99,
        clip_param=0.2,
        actor_batch_size=8,
        epochs=1000,
        lr_policy=0.001,
        lr_value=0.005,
        policy_copy_interval=20,
        save_interval=200,
        tensorboard_log=None,
        seed=None,
        render=False,
        device="cpu",
        pretrained=False,
        save_name=None,
        save_version=None,
    ):
        self.policy = policy
        self.value = value
        self.env = env
        self.timesteps_per_actorbatch = timesteps_per_actorbatch
        self.gamma = gamma
        self.clip_param = clip_param
        self.actor_batch_size = actor_batch_size
        self.epochs = epochs
        self.lr_policy = lr_policy
        self.lr_value = lr_value
        self.tensorboard_log = tensorboard_log
        self.seed = seed
        self.render = render
        self.policy_copy_interval = policy_copy_interval
        self.save_interval = save_interval
        self.pretrained = pretrained
        self.save_name = save_name
        self.save_version = save_version
        self.save = save_params
        self.load = load_params
        self.checkpoint = self.__dict__

        # Assign device
        if "cuda" in device and torch.cuda.is_available():
            self.device = torch.device(device)
        else:
            self.device = torch.device("cpu")

        # Assign seed
        if seed is not None:
            torch.manual_seed(seed)
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
            np.random.seed(seed)
            self.env.seed(seed)

        # init writer if tensorboard
        self.writer = None
        if self.tensorboard_log is not None:
            from torch.utils.tensorboard import SummaryWriter

            self.writer = SummaryWriter(log_dir=self.tensorboard_log)

        self.create_model()

    def create_model(self):
        # Instantiate networks and optimizers
        self.policy_fn = get_policy_from_name(self.policy)(self.env)
        self.policy_fn.to(self.device)
        self.value_fn = get_value_from_name(self.value)(self.env)
        self.value_fn.to(self.device)

        # load paramaters if already trained
        if self.pretrained:
            self.load(self)
            self.policy_fn.load_state_dict(self.checkpoint["policy_weights"])
            self.value_fn.load_state_dict(self.checkpoint["value_weights"])
            for key, item in self.checkpoint.items():
                if key not in ["policy_weights", "value_weights"]:
                    setattr(self, key, item)

        self.optimizer_policy = opt.Adam(
            self.policy_fn.parameters(), lr=self.lr_policy
        )
        self.optimizer_value = opt.Adam(
            self.value_fn.parameters(), lr=self.lr_value
        )

    def select_action(self, s):
        state = torch.from_numpy(s).float().to(self.device)

        # create distribution based on policy_fn output
        action, c = self.policy_fn.sample_action(Variable(state))
        val = self.value_fn(Variable(state))

        # store policy probs and value function for current traj
        self.policy_fn.policy_hist = torch.cat(
            [self.policy_fn.policy_hist, c.log_prob(action).unsqueeze(0), ]
        )

        self.value_fn.value_hist = torch.cat([self.value_fn.value_hist, val])

        return action

    # get clipped loss for single trajectory (episode)
    def get_traj_loss(self):
        R = 0
        returns = []

        # calculate discounted return
        for r in self.policy_fn.traj_reward[::-1]:
            R = r + self.gamma * R
            returns.insert(0, R)

        # advantage estimation
        returns = torch.FloatTensor(returns).to(self.device)
        A = Variable(returns) - Variable(self.value_fn.value_hist)

        # compute policy and value loss
        loss_policy = (
            torch.sum(torch.mul(
                self.policy_fn.policy_hist, A
            )).mul(-1).unsqueeze(0)
        )

        loss_value = nn.MSELoss()(
            self.value_fn.value_hist, Variable(returns)
        ).unsqueeze(0)

        # store traj loss values in epoch loss tensors
        self.policy_fn.loss_hist = torch.cat(
            [self.policy_fn.loss_hist, loss_policy]
        )
        self.value_fn.loss_hist = torch.cat(
            [self.value_fn.loss_hist, loss_value]
        )

        # clear traj history
        self.policy_fn.traj_reward = []
        self.policy_fn.policy_hist = Variable(torch.Tensor())
        self.value_fn.value_hist = Variable(torch.Tensor())

    def update_policy(self, ep):
        # mean of all traj losses in single epoch
        loss_policy = torch.mean(self.policy_fn.loss_hist)
        loss_value = torch.mean(self.value_fn.loss_hist)

        # tensorboard book-keeping
        if self.tensorboard_log:
            self.writer.add_scalar("loss/policy", loss_policy, ep)
            self.writer.add_scalar("loss/value", loss_value, ep)

        # take gradient step
        self.optimizer_policy.zero_grad()
        loss_policy.backward()
        self.optimizer_policy.step()

        self.optimizer_value.zero_grad()
        loss_value.backward()
        self.optimizer_value.step()

        # clear loss history for epoch
        self.policy_fn.loss_hist = Variable(torch.Tensor())
        self.value_fn.loss_hist = Variable(torch.Tensor())

    def learn(self):
        # training loop
        for episode in range(self.epochs):
            epoch_reward = 0
            for _ in range(self.actor_batch_size):
                state = self.env.reset()
                done = False
                for _ in range(self.timesteps_per_actorbatch):
                    action = self.select_action(state)
                    state, reward, done, _ = self.env.step(np.array(action))

                    if self.render:
                        self.env.render()

                    self.policy_fn.traj_reward.append(reward)

                    if done:
                        break

                epoch_reward += (
                    np.sum(self.policy_fn.traj_reward) / self.actor_batch_size
                )
                self.get_traj_loss()

            self.update_policy(episode)

            if episode % 20 == 0:
                print("Episode: {}, reward: {}".format(episode, epoch_reward))
                if self.tensorboard_log:
                    self.writer.add_scalar("reward", epoch_reward, episode)

            if episode % self.save_interval == 0:
                self.checkpoint["policy_weights"] = self.policy_fn.state_dict()
                self.checkpoint["value_weights"] = self.value_fn.state_dict()
                if self.save_name is None:
                    self.save_name = "{}-{}".format(self.policy, self.value)
                self.save_version = int(episode / self.save_interval)
                self.save(self)

        self.env.close()
        if self.tensorboard_log:
            self.writer.close()


if __name__ == "__main__":
    env = gym.make("CartPole-v1")
    algo = VPG("MlpPolicy", "MlpValue", env, epochs=500, save_name="VPG")
    algo.learn()
