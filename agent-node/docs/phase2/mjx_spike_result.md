# P2.2 spike — MJX datapoint (2026-06-13)

k8s GPU job on worker (RTX 4060, host-network pod): MJX strut-pendulum, 1024 parallel envs x 200 steps in 0.19s = **1,050,751 env-steps/s** (toy 1-DOF scene; JIT-compiled vmap step). Pipeline proven: namespace-scoped job -> nvidia runtimeClass -> jax[cuda12]. P2.8 exit threshold (>8k env-steps/s at 512 envs) trivially exceeded for this scene; real multi-body attach/detach scenes will be orders slower — Isaac half of the spike still required.
