# How to use a custom extraction schema

A custom JSON Schema makes the `data` object predictable for downstream systems. Select
**Paste** or **Upload** under **Extraction schema**, then provide a schema no larger than 100 KB.

## Start with a strict object schema

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "invoice_number": {
      "type": ["string", "null"]
    },
    "invoice_date": {
      "type": ["string", "null"]
    },
    "total": {
      "type": ["number", "null"]
    }
  },
  "required": ["invoice_number", "invoice_date", "total"]
}
```

Use `null` in a property's type when the document may not contain the value. Every property
must still appear in `required` because the model uses strict Structured Outputs.

## Follow the supported subset

Every object in the schema must:

- use `"type": "object"`;
- define `properties` as an object;
- set `"additionalProperties": false`; and
- list every property name in `required`.

The application rejects `$ref`. Define nested objects inline and apply the same strict-object
rules at every level. These are the constraints validated locally; the configured Structured
Outputs endpoint may reject additional JSON Schema keywords it does not implement.

For nested arrays, define the item object inline:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "line_items": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "description": {"type": ["string", "null"]},
          "amount": {"type": ["number", "null"]}
        },
        "required": ["description", "amount"]
      }
    }
  },
  "required": ["line_items"]
}
```

| Constraint | Local behavior |
|---|---|
| Root type is not `object` | Rejected |
| Object omits `additionalProperties: false` | Rejected |
| Object does not require every property | Rejected |
| `$ref` appears at any depth | Rejected |
| Schema exceeds 100 KB | Rejected |
| Other valid JSON Schema keywords | Passed locally; endpoint support still applies |

## Combine instructions with a schema

The schema controls shape and types; instructions control interpretation. For example:

```text
Use the final amount due after discounts as total. Return dates exactly as printed.
```

Do not ask the model to invent unavailable values. Optional values should allow `null`.

## Verify the result

Open the **JSON** tab and check:

1. `data` follows the supplied schema.
2. Every non-null leaf has an entry in `evidence`.
3. Each evidence quote appears in its cited source lines.
4. `status` is `complete` only when no issues remain.

If local evidence validation fails, the model receives one retry with validation feedback. A
second invalid result becomes `partial` when usable data remains or `failed` otherwise.

See the [output JSON reference](../reference/output-json.md) for the complete envelope.
