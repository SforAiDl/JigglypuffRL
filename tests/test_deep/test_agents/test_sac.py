import shutil

from genrl import SAC
from genrl.deep.common import MlpActorCritic, MlpPolicy, MlpValue, OffPolicyTrainer
from genrl.environments import VectorEnv


def test_sac():
    env = VectorEnv("Pendulum-v0", 2)
    algo = SAC("mlp", env, layers=[1, 1])

    trainer = OffPolicyTrainer(algo, env, log_mode=["csv"], logdir="./logs", epochs=1)
    trainer.train()
    shutil.rmtree("./logs")


class custom_net(MlpActorCritic):
    def __init__(self, state_dim, action_dim, **kwargs):
        super(custom_net, self).__init__(
            state_dim, action_dim, kwargs.get("hidden"), val_type="Qsa", discrete=False
        )
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.policy = MlpPolicy(
            state_dim, action_dim, kwargs.get("hidden"), False, sac=True
        )
        self.value = self.critic


def test_sac_custom():
    env = VectorEnv("Pendulum-v0", 2)
    algo = SAC(
        custom_net(
            state_dim=env.observation_space.shape[0],
            action_dim=env.action_space.shape[0],
            hidden=(1, 1),
        ),
        env,
    )
    trainer = OffPolicyTrainer(algo, env, log_mode=["csv"], logdir="./logs", epochs=1)
    trainer.train()
    shutil.rmtree("./logs")
