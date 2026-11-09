# Build with the patched upstream dify_agent source directory as the context.
FROM langgenius/dify-agent-backend@sha256:80d638d7114bb0fbe954952e37da1f464b61969ff870c0b173963b9f2b91e06e

# Refuse to overlay a different upstream implementation.
RUN python -c 'from pathlib import Path; import hashlib; root=Path("/app/api/.venv/lib/python3.13/site-packages/dify_agent"); checks={"layers/shell/layer.py":"58d8ffb40f84413d972b08a7d4be9637cf584d48192bb886e4ebc83ee47823de","server/sse.py":"3c7ffd9a36b9267c5f32ced6f15093a3d99141cdf891315294f19f35bc73ca32"}; assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==value for name,value in checks.items())'

COPY layers/shell/layer.py /app/api/.venv/lib/python3.13/site-packages/dify_agent/layers/shell/layer.py
COPY server/sse.py /app/api/.venv/lib/python3.13/site-packages/dify_agent/server/sse.py

RUN python -c 'from pathlib import Path; import hashlib,ast; root=Path("/app/api/.venv/lib/python3.13/site-packages/dify_agent"); checks={"layers/shell/layer.py":"2d7d8729bafeda7cd882598819e2adbfdfe15c6055985356376cc8397933c3ac","server/sse.py":"075cdf842b66d9439cbd89eac4a4cc9e723b546e1c3697914e25b7f20d0cbd12"}; assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==value for name,value in checks.items()); [ast.parse((root/name).read_text()) for name in checks]'

LABEL org.opencontainers.image.title="Dify 1.18.0 pilot shell cancellation fix" \
      org.opencontainers.image.revision="50abea97062110044f15d0e03ccecadd9ccc87ca+shell-cancel-fix"
