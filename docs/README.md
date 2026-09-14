# Documentation

Use this page to choose the shortest path to your goal. The documentation follows the
[Diátaxis](https://diataxis.fr/) separation between learning, tasks, reference, and explanation.

## Start here

- New user: [Process your first scanned document](tutorials/first-document.md)
- Returning user: [Process documents and batches](how-to/process-documents.md)
- Schema user: [Use a custom extraction schema](how-to/use-a-custom-schema.md)
- Contributor: [Architecture](codebase/architecture.md) and
  [Contributing](../CONTRIBUTING.md)

## Tutorials

| Goal | Document |
|---|---|
| Complete one guided parse and optional extraction | [First document](tutorials/first-document.md) |

## How-to guides

| Goal | Document |
|---|---|
| Install, start, and stop the app | [Run the app](how-to/run-the-app.md) |
| Upload files, select pages, and download results | [Process documents](how-to/process-documents.md) |
| Compare OCR policies against the fixed reference suite | [Evaluate accuracy](how-to/evaluate-accuracy.md) |
| Extract data into a defined shape | [Use a custom schema](how-to/use-a-custom-schema.md) |
| Resolve common startup and processing failures | [Troubleshooting](how-to/troubleshooting.md) |

## Reference

| Lookup | Document |
|---|---|
| Environment, fixed settings, formats, and limits | [Configuration](reference/configuration.md) |
| JSON schema v2.2, evidence, statuses, repairs, and issues | [Output JSON](reference/output-json.md) |
| Modules, types, and internal callables | [Python internals](reference/python-internals.md) |

## Explanation and operations

- [Understanding LiteParse](explanation/understanding-liteparse.md)
- [Architecture](codebase/architecture.md)
- [Processing flow](codebase/processing-flow.md)
- [300/400-DPI repair strategy](codebase/repair-strategy.md)
- [Evidence-grounded extraction](codebase/extraction-strategy.md)
- [Data contracts](codebase/data-contracts.md)
- [Operations](codebase/operations.md)
- [Testing](codebase/testing.md)

## Research knowledge

The separate [project knowledge index](../knowledge/index.md) contains provider research and
document-processing concepts. Its entries are currently **draft and unverified**. Use current
source and tests as authority for application behavior.

## Documentation coverage

| Reader need | Canonical page |
|---|---|
| Understand the product quickly | [Root README](../README.md) |
| Reach a first successful result | [First document](tutorials/first-document.md) |
| Operate the UI efficiently | [Process documents](how-to/process-documents.md) |
| Control extracted fields | [Custom schema](how-to/use-a-custom-schema.md) |
| Interpret success and degradation | [Output JSON](reference/output-json.md) |
| Diagnose a problem | [Troubleshooting](how-to/troubleshooting.md) |
| Understand or change the implementation | [Architecture](codebase/architecture.md) |
| Learn what LiteParse does and how it is used | [Understanding LiteParse](explanation/understanding-liteparse.md) |
| Validate and contribute changes | [Contributing](../CONTRIBUTING.md) |
