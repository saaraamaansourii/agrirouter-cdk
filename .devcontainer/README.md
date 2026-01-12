# Dev Container (AWS CDK TypeScript)

This project uses:
- Node.js **v24** (see `.node-version`)
- AWS CLI **v2**
- CDK bundling with Docker (Lambda layers are built via `lambda.Runtime.PYTHON_3_11.bundlingImage`)

## Requirements (host)
- Docker Desktop / Docker Engine running
- VS Code + **Dev Containers** extension
- AWS credentials available on the host in `~/.aws` (profiles or SSO)

## Notes
- The dev container mounts:
  - `~/.aws` into the container (so `--profile ...` works)
  - `/var/run/docker.sock` into the container (so CDK bundling works)

## Quick checks (inside container)
```bash
node -v
aws --version
npx cdk --version
aws sts get-caller-identity --profile YOUR_PROFILE
npx cdk synth --profile YOUR_PROFILE
```

## If Docker bundling fails
Make sure Docker is running on your host, and that VS Code has permission to access it.
