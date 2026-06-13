"""Launch the MJX GPU micro-benchmark as a k8s job on the worker (P2.2 spike,
MJX half). Script travels via env var — no shell-quoting, no ConfigMap."""
from run_k8s import submit_job

BENCH = r'''
import time, jax, mujoco
import jax.numpy as jnp
from mujoco import mjx

print("devices:", jax.devices())
XML = """
<mujoco>
  <option timestep="0.004"/>
  <worldbody>
    <body pos="0 0 1">
      <joint type="hinge" axis="1 0 0"/>
      <geom type="capsule" size="0.02" fromto="0 0 0 0 0 0.22" mass="0.35"/>
    </body>
  </worldbody>
</mujoco>
"""
m = mujoco.MjModel.from_xml_string(XML)
mx = mjx.put_model(m)
B = 1024
data = jax.vmap(lambda _: mjx.make_data(mx))(jnp.arange(B))
step = jax.jit(jax.vmap(lambda d: mjx.step(mx, d)))
data = step(data); jax.block_until_ready(data.qpos)   # compile
t0 = time.time()
for _ in range(200):
    data = step(data)
jax.block_until_ready(data.qpos)
dt = time.time() - t0
print(f"MJX strut-pendulum: {B} envs x 200 steps in {dt:.2f}s "
      f"= {B*200/dt:,.0f} env-steps/s")
'''

ok, logs = submit_job(
    "mjx-spike", "python:3.11-slim",
    ["bash", "-c",
     'pip install -q mujoco mujoco-mjx "jax[cuda12]" 2>&1 | tail -1 && '
     'python3 -c "import os; exec(os.environ[\'BENCH\'])"'],
    gpu=True, host_network=True, timeout=1700,
    env={"BENCH": BENCH})
print("JOB-SUCCEEDED" if ok else "JOB-FAILED")
print(logs[-500:])
