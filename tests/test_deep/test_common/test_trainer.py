from genrl import PPO1, TD3, CovertypeDataBandit, NeuralGreedyAgent
from genrl.deep.common import BanditTrainer, OffPolicyTrainer, OnPolicyTrainer
from genrl.environments import VectorEnv


def test_on_policy_trainer():
    env = VectorEnv("CartPole-v1", 2)
    algo = PPO1("mlp", env)
    trainer = OnPolicyTrainer(algo, env, ["stdout"], epochs=1)
    assert not trainer.off_policy
    trainer.train()


def test_off_policy_trainer():
    env = VectorEnv("Pendulum-v0", 2)
    algo = TD3("mlp", env)
    trainer = OffPolicyTrainer(algo, env, ["stdout"], epochs=1)
    assert trainer.off_policy
    trainer.train()


def test_bandit_policy_trainer():
    bandit = CovertypeDataBandit(download=True)
    agent = NeuralGreedyAgent(bandit)
    trainer = BanditTrainer(agent, bandit, log_mode=["stdout"])
    trainer.train(timesteps=10, update_interval=2, update_after=5, batch_size=2)
