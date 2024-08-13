# Developer Documentation

* [Getting started](#getting-started)
    - [How to create a design doc](#how-to-create-a-design-doc)
    - [Goals when designing a new feature](#goals-when-designing-new-features)
* [Creating a pull request](#creating-a-pull-request)
* [Releasing](#releasing)

## Getting started

Usually a good starting point is to create a design document that covers the goals, impacts and technical details of the new feature being proposed. In case it's just a very small feature or a bugfix, a PR can be created directly in the Cachi2 repository, as long as the PR description contains all the necessary context and information needed by the reviewers.

### How to create a design doc

New design docs should be proposed as pull requests to the `docs/design` folder of this repository. Check the template present in this folder to help you get started. 

The discussions about the design should occur in the context of the PR itself. All designs need two approvals before they are accepted, and once a design is merged, it also means that it's status is `approved`.

An `approved design` is immutable, any further changes to the design should be done in a follow-up document. The only changes allowed to an already merged design doc are status updates, which should reflect what other documents are appending to or superceeding the current one.

### Goals when designing new features

Cachi2 has the primary goal of safely enabling hermetic builds. For this purpose, Cachi2 needs to prefetch content  and very accurately describe what was downloaded. These are important topics to keep in mind when design a Cachi2 feature:

- Arbitrary code execution: whenever we're executing built-in commands in any existing package manager, there's a chance that arbitrary code will be executed. That is the case for the code in `setup.py` when we execute `pip install` or the npm lifecycle scripts, such as `postinstall` or `preinstall`. Arbitrary code is a great breach for security, and makes it impossible to guarantee that unexpected content was downloaded from the internet. For this reason, all arbitrary code execution is banned in Cachi2. Be very thorough to investigate the use of built-in commands in Cachi2, and make it clear in your design how it was investigate, and how the arbitrary code execution can be avoided.

- Build from an offline cache: Cachi2 should not only provide the files needed for an offline install, but also provide all the configuration needed to perform the build. That might involve the use of environment variables or even changing some configuration files in the repository. For that purpose, Cachi2 makes use of two commands: `generate-env`, for generating the necessary environment variables, and `inject-files`, for actually modifying the necessary files in the target repository.

- Checksum validation: 

- Pre-compiled binaries:

- Reproducibility:

## Creating a pull request

### Coding standards

Cachi2's codebase conforms to standards enforced by a collection of formatters, linters and other code checkers:

* [black](https://black.readthedocs.io/en/stable/) (with a line-length of 100) for consistent formatting
* [isort](https://pycqa.github.io/isort/) to keep imports sorted
* [flake8](https://flake8.pycqa.org/en/latest/) to (de-)lint the code and ~~politely~~ ask for docstrings
* [mypy](https://mypy.readthedocs.io/en/stable/) for type-checking. Please include type annotations for new code.
* [pytest](https://docs.pytest.org/en/7.1.x/) to run unit tests and report coverage stats. Please aim for (near) full
  coverage of new code.

Options for all the tools are configured in [pyproject.toml](./pyproject.toml) and [tox.ini](./tox.ini).

Run all the checks that your pull request will be subjected to:

```shell
make test
```

### Error message guidelines

We try to keep error messages friendly and actionable.

* If there is a known solution, the error message should politely suggest the solution.
  * Include a link to the documentation when suitable.
* If there is no known solution, suggest where to look for help.
* If retrying is a possible solution, suggest retrying and where to look for help if the issue persists.

The error classes aim to encourage these guidelines. See the [errors.py](cachi2/core/errors.py) module.

### Developer flags

* `--dev-package-managers` (hidden): enables in-development package manager(s)
  for test. Please refer to other existing package managers to see how they're
  enabled and wired to the CLI.

  Invoke it as `cachi2 fetch-deps --dev-package-managers FOO`

  More explicitly

  * `--dev-package-managers` is a *flag for* `fetch-deps`
  * `FOO` is an *argument to* `fetch-deps` (i.e. the language to fetch for)

### Running unit tests

Run all unit tests (but no other checks):

```shell
make test-unit
```

For finer control over which tests get executed, e.g. to run all tests in a specific file, activate
the [virtualenv](#virtual-environment) and run:

```shell
tox -e py39 -- tests/unit/test_cli.py
```

Even better, run it stepwise (exit on first failure, re-start from the failed test next time):

```shell
tox -e py39 -- tests/unit/test_cli.py --stepwise
```

You can also run a single test class or a single test method:

```shell
tox -e py39 -- tests/unit/test_cli.py::TestGenerateEnv
tox -e py39 -- tests/unit/test_cli.py::TestGenerateEnv::test_invalid_format
tox -e py39 -- tests/unit/extras/test_envfile.py::test_cannot_determine_format
```

In short, tox passes all arguments to the right of `--` directly to pytest.

### Running integration tests

Build Cachi2 image (localhost/cachi2:latest) and run most integration tests:

```shell
make test-integration
```

Run tests which requires a local PyPI server as well:

```shell
make test-integration TEST_LOCAL_PYPISERVER=true
```

Note: while developing, you can run the PyPI server with `tests/pypiserver/start.sh &`.

To run integration-tests with custom image, specify the CACHI2\_IMAGE environment variable. Examples:

```shell
CACHI2_IMAGE=quay.io/redhat-appstudio/cachi2:{tag} tox -e integration
CACHI2_IMAGE=localhost/cachi2:latest tox -e integration
```

Similarly to unit tests, for finer control over which tests get executed, e.g. to run only 1 specific test case, execute:

```shell
tox -e integration -- tests/integration/test_package_managers.py::test_packages[gomod_without_deps]
```

### Running integration tests and generating new test data

To re-generate new data (output, dependencies checksums, vendor checksums) and run integration tests with them:

```shell
make GENERATE_TEST_DATA=true test-integration
```

Generate data for test cases matching a pytest pattern:

```shell
CACHI2_GENERATE_TEST_DATA=true tox -e integration -- -k gomod
```

### Adding new dependencies to the project

Sometimes when working on adding a new feature you may need to add a new dependency to the project.
Usually, one commonly goes about it by adding the dependency to one of the ``requirements`` files
or the more modern and standardized ``pyproject.toml`` file.
In our case, dependencies must always be added to the ``pyproject.toml`` file as the
``requirements`` files are generated by the ``pip-compile`` tool to not only pin versions of all
dependencies but also to resolve and pin transitive dependencies. Since our ``pip-compile``
environment is tied to Python 3.9, we have a Makefile target that runs the tool in a container
image so you don't have to install another Python version locally just because of this. To
re-generate the set of dependencies, run the following in the repository and commit the changes:

```
$ make pip-compile
```

## Releasing

To release a new version of Cachi2, simply create a [GitHub release][cachi2-releases]. Note that
Cachi2 follows [semantic versioning](https://semver.org/) rules.

Upon release, the [.tekton/release.yaml](.tekton/release.yaml) pipeline tags the corresponding
[Cachi2 image][cachi2-container] with the newly released version tag (after validating that the
tag follows the expected format: `$major.$minor.$patch`, without a `v` prefix).

*You apply a release tag to a specific commit. The [.tekton/push.yaml](.tekton/push.yaml) pipeline
should have built the image for that commit already. This is the "corresponding image" that receives
the new version tag. If the image for the tagged commit does not exist, the release pipeline will fail.*

You can watch the release pipeline in the [OpenShift console][ocp-cachi2-pipelines] in case it fails
(the pipeline is not visible anywhere in GitHub UI). For intermittent failures, retrying should be
possible from the OpenShift UI or by deleting and re-pushing the version tag.

*⚠ The release pipeline runs as soon as you push a tag into the repository. Do not push the new version
tag until you are ready to publish the release. You can use GitHub's ability to auto-create the tag
upon publishment.*
