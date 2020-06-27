import torch
from scipy.stats import invgamma

from ..data_bandits import DataBasedBandit
from .common import TransitionDB
from .dcb_agent import DCBAgent

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
dtype = torch.float


class LinearPosteriorAgent(DCBAgent):
    def __init__(
        self,
        bandit: DataBasedBandit,
        init_pulls: int = 3,
        lambda_prior: float = 0.5,
        a0: float = 0.0,
        b0: float = 0.0,
        bayesian_update_interval: int = 1,
    ):
        super(LinearPosteriorAgent, self).__init__(bandit)

        self.init_pulls = init_pulls
        self.lambda_prior = lambda_prior
        self.a0 = a0
        self.b0 = b0
        self.mu = torch.zeros(
            size=(self.n_actions, self.context_dim + 1), device=device, dtype=dtype
        )
        self.cov = torch.stack(
            [
                (1.0 / self.lambda_prior)
                * torch.eye(self.context_dim + 1, device=device, dtype=dtype)
                for _ in range(self.n_actions)
            ]
        )
        self.inv_cov = torch.stack(
            [
                self.lambda_prior
                * torch.eye(self.context_dim + 1, device=device, dtype=dtype)
                for _ in range(self.n_actions)
            ]
        )
        self.a = self.a0 * torch.ones(self.n_actions, device=device, dtype=dtype)
        self.b = self.b0 * torch.ones(self.n_actions, device=device, dtype=dtype)
        self.db = TransitionDB()
        self.bayesian_update_interval = bayesian_update_interval
        self.t = 0
        self.update_count = 0

    def select_action(self, context: torch.Tensor) -> int:
        self.t += 1
        if self.t < self.n_actions * self.init_pulls:
            return torch.tensor(self.t % self.n_actions, device=device, dtype=torch.int)

        var = torch.tensor(
            [self.b[i] * invgamma.rvs(self.a[i]) for i in range(self.n_actions)],
            device=device,
            dtype=dtype,
        )
        try:
            beta = (
                torch.stack(
                    [
                        torch.distributions.MultivariateNormal(
                            self.mu[i], var[i] * self.cov[i]
                        ).sample()
                        for i in range(self.n_actions)
                    ]
                )
                .to(device)
                .to(dtype)
            )
        except RuntimeError as e:  # noqa F841
            # print(f"Eror: {e}")
            beta = (
                torch.stack(
                    [
                        torch.distributions.MultivariateNormal(
                            torch.zeros(self.context_dim + 1),
                            torch.eye(self.context_dim + 1),
                        ).sample()
                        for i in range(self.n_actions)
                    ]
                )
                .to(device)
                .to(dtype)
            )
        values = torch.mv(beta, torch.cat([context.squeeze(0), torch.ones(1)]))
        return torch.argmax(values).to(torch.int)

    def update_params(self, context: torch.Tensor, action: int, reward: int):
        self.update_count += 1
        self.db.add(context, action, reward)

        if self.update_count % self.bayesian_update_interval == 0:
            x, y = self.db.get_data_for_action(action)
            x = torch.cat([x, torch.ones(x.shape[0], 1)], dim=1)
            inv_cov = torch.mm(x.T, x) + self.lambda_prior * torch.eye(
                self.context_dim + 1
            )
            cov = torch.inverse(inv_cov)
            mu = torch.mm(cov, torch.mm(x.T, y))
            a = self.a0 + self.t / 2
            b = self.b0 + (torch.mm(y.T, y) - torch.mm(mu.T, torch.mm(inv_cov, mu))) / 2
            self.mu[action] = mu.squeeze(1)
            self.cov[action] = cov
            self.inv_cov[action] = inv_cov
            self.a[action] = a
            self.b[action] = b


if __name__ == "__main__":

    from .common import demo_dcb_policy
    from ..data_bandits.covertype_bandit import CovertypeDataBandit
    from ..data_bandits.mushroom_bandit import MushroomDataBandit
    from ..data_bandits.statlog_bandit import StatlogDataBandit
    from ..contextual_bandits import BernoulliCB

    TIMESTEPS = 50_000
    ITERATIONS = 1
    BANDIT_ARGS = {"download": True}
    # BANDIT_ARGS = {"bandits": 10, "arms": 10}

    POLICY_ARGS_COLLECTION = [
        {
            "init_pulls": 2,
            "lambda_prior": 0.25,
            "a0": 0.0,
            "b0": 0.0,
            "bayesian_update_interval": 1,
        }
    ]

    demo_dcb_policy(
        LinearPosteriorAgent,
        MushroomDataBandit,
        POLICY_ARGS_COLLECTION,
        BANDIT_ARGS,
        TIMESTEPS,
        ITERATIONS,
        verbose=True,
    )
