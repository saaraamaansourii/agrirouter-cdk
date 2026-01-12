# Agrirouter API specifications

All internal API specifications for communications between internal agrirouter components are placed here.

The repository is located here: https://github.com/DKE-Data/agrirouter-api-specs

## Overview

The structure of this repository is following:

- openapi
  - service1/
    - service1-specific.yaml
  - service2/
    - service2-specific.yaml
  - ...
- proto
  - service1/
    - service1-specific.proto
    - some-other-spec.proto
  - service2/
    - service2-specific.proto
  - ...
  - common.proto // if need this
  - other-common.proto
- topics
  - topics.go

### OpenAPI

Folder `openapi` is where all [OpenAPI](https://spec.openapis.org/oas/latest.html) specifications are located that are used within agrirouter between the components that use HTTP to communicate.

When frontend communicates with backend microservice over HTTP, both should rely on same specification.

### Proto

Folder `proto` is where all [Protocol Buffers](https://protobuf.dev/) specifications are located that are used within agrirouter between the components that use Protocol Buffers as a serialization medium (binary or json encoding).

Microservices that send each other JSON or binary protobuf encoded messages over event bus shall use specifications in proto directory.

### Topics
Please use and update the constants inside of here when you produce or consume Kafka Messages. The import might not work right away from saving, so you can copy with this:

```
"github.com/DKE-Data/agrirouter-SERVICENAME-service/api/topics"
```

## Install git hooks

After cloning argirouter-api-specs repository first time, run this command:

```bash
git config core.hooksPath githooks
```

It would install git hooks that would run linter on every commit.

### Proto breaking changes

By default hooks would attempt to block commit if there are breaking changes in proto files. If you want to commit anyway, you can use ALLOW_BREAK_PROTO environment variable to skip this check:

```bash
ALLOW_BREAK_PROTO=1 git commit -m "Some commit message"
```

## Linting

First of all you would need to install linters:

```bash
npm ci
```

### OpenAPI

To lint the OpenAPI specifications before commiting, you can use the following command:

```bash
tools/openapi_lint.sh
```

It would validate only modified or staged files from openapi folder, which have OpenAPI files extensions (yaml, yml, json).
It would ignore files that do not have expected OpenAPI format.

Alternatively you can run something like this:

```bash
npx spectral lint 'openapi/**/*.yaml'
```
to check for all files in openapi folder and ignoring unknown formats:

```bash
npx spectral lint --ignore-unknown-format 'openapi/**/*.yaml'
```

### Proto

To lint the Protocol Buffers specifications before commiting, you can use the following command:

```bash
tools/proto_lint.sh
```

It validates, however, all proto files in the repository, not only the modified ones.

#### Detect breaking changes

If you run 
```bash
tools/proto_breaking.sh
```
, it would report breaking changes in proto files you have modified against git head.


## Using in service

Include as subtree eg. like this:

```bash
git subtree add --prefix api https://github.com/DKE-Data/agrirouter-api-specs.git main --squash
```
or
```bash
git subtree add --prefix api git@github.com:DKE-Data/agrirouter-api-specs.git main --squash
```

🚨 To change specifications, changes MUST always be made in the agrirouter-api-specs repository.

To pull updates into a service repository at a later date:

```bash
git subtree pull --prefix api https://github.com/DKE-Data/agrirouter-api-specs.git main --squash
```
or
```bash
git subtree pull --prefix api git@github.com:DKE-Data/agrirouter-api-specs.git main --squash
```
