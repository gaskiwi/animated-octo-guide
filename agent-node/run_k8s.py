"""
run_k8s.py — namespace-scoped K8s job runner for the swarm.

Submits batch Jobs to the `agents` namespace using the restricted
agent-runner ServiceAccount kubeconfig (AGENT_KUBECONFIG, mounted
read-only). GPU jobs land on the worker via runtimeClass `nvidia`.
Agents cannot see or touch anything outside the `agents` namespace.

Library use:
    from run_k8s import submit_job
    ok, logs = submit_job("train-smoke", "busybox:stable",
                          ["echo", "hello"], gpu=False)

CLI smoke test:
    python3 run_k8s.py --image busybox:stable --cmd "echo hello" [--gpu]
"""
import logging
import os
import sys
import time
import uuid

log = logging.getLogger("run_k8s")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

NAMESPACE = os.environ.get("AGENT_K8S_NAMESPACE", "agents")
KUBECONFIG = os.environ.get("AGENT_KUBECONFIG", "/app/secrets/agent-kubeconfig.yaml")


def _clients():
    from kubernetes import client, config
    config.load_kube_config(KUBECONFIG)
    return client.BatchV1Api(), client.CoreV1Api(), client


def submit_job(name: str, image: str, command: list[str], gpu: bool = False,
               timeout: int = 3600, env: dict | None = None):
    """Create a Job, wait for completion, return (succeeded, logs)."""
    batch, core, k = _clients()
    job_name = f"{name[:40]}-{uuid.uuid4().hex[:6]}".lower().replace("_", "-")

    container = k.V1Container(
        name="main", image=image, command=command,
        env=[k.V1EnvVar(name=n, value=v) for n, v in (env or {}).items()],
        resources=k.V1ResourceRequirements(
            limits={"nvidia.com/gpu": "1"} if gpu else None))
    pod_spec = k.V1PodSpec(
        restart_policy="Never", containers=[container],
        runtime_class_name="nvidia" if gpu else None)
    job = k.V1Job(
        metadata=k.V1ObjectMeta(name=job_name, namespace=NAMESPACE),
        spec=k.V1JobSpec(
            backoff_limit=0, ttl_seconds_after_finished=3600,
            active_deadline_seconds=timeout,
            template=k.V1PodTemplateSpec(spec=pod_spec)))

    batch.create_namespaced_job(NAMESPACE, job)
    log.info("job %s submitted (gpu=%s, image=%s)", job_name, gpu, image)

    deadline = time.time() + timeout + 120
    succeeded = False
    while time.time() < deadline:
        st = batch.read_namespaced_job_status(job_name, NAMESPACE).status
        if st.succeeded:
            succeeded = True
            break
        if st.failed:
            break
        time.sleep(5)

    logs = ""
    try:
        pods = core.list_namespaced_pod(
            NAMESPACE, label_selector=f"job-name={job_name}").items
        if pods:
            logs = core.read_namespaced_pod_log(
                pods[0].metadata.name, NAMESPACE, tail_lines=200)
    except Exception as e:
        logs = f"(log fetch failed: {e})"
    log.info("job %s %s", job_name, "succeeded" if succeeded else "FAILED")
    return succeeded, logs


if __name__ == "__main__":
    args = sys.argv[1:]
    def _val(flag, default):
        return args[args.index(flag) + 1] if flag in args else default
    image = _val("--image", "busybox:stable")
    cmd = _val("--cmd", "echo hello from the agents namespace").split()
    ok, logs = submit_job("cli", image, cmd, gpu="--gpu" in args)
    print(f"succeeded={ok}\n--- logs ---\n{logs}")
    sys.exit(0 if ok else 1)
