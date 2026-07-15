# Prompt Documentation

## Scope

The pipeline uses LLMs in bounded roles. AI output is not treated as independent verification evidence. Structured identifiers, URLs, source fields, external enrichment, and validation rules remain necessary.

## 1. Collection-stage template

The exact wording used across every historical collection session was not stored as one immutable prompt in the archived code snapshot. The following is a documentation template reconstructed from the operational rules and should not be presented as a verbatim historical prompt:

```text
Identify a real company that satisfies the specified region, sector,
industry, subindustry, activity-status, and size conditions.

Return the required CSV fields only. Use a valid 10- or 12-digit INN.
Provide an official company website where available and identify the
source used to verify registration and company status.

Do not invent missing values. If a required identifier or threshold
cannot be verified, do not treat the company as confirmed.
```

## 2. Description-editor system prompt

The mature description builder contains the following system-level rules:

```text
You are an editor of corporate descriptions.
Use only the supplied fields.
Do not search the internet or add unsupported facts.
Do not narrate source names inside the description.
Use a neutral business style without advertising.
```

The implementation prompt is written in Russian because the generated company descriptions were Russian-language records.

## 3. Description-editor user instructions

The main constraints implemented in `description_builder.py` are:

- exactly four sentences;
- target length of approximately 500–650 characters;
- the first sentence states name, year where available, region/city, and role or activity;
- the second sentence describes geography or regional connection;
- the third sentence uses a concrete function, asset, service, or infrastructure fact from the supplied fields;
- the fourth sentence is copied exactly from the rule-generated text;
- no unsupported facts;
- no links or explanatory commentary;
- no source narration such as “according to open data”;
- no promotional terms such as “leader”, “best”, “unique”, or “dynamically developing”;
- output contains only the description.

The structured payload may include identity, classification, region, address, activity, website, employee, revenue, foundation-year, and SPARK evidence fields.

## 4. Rule-based fallback

If YandexGPT credentials are unavailable, the pipeline does not stop. It generates a rule-based description and records the mode and quality conditions. This makes the LLM editor optional rather than a required dependency.

## 5. Validation prompt template

For independent review of a generated description, the following template can be used:

```text
Compare the description only with the supplied structured fields.

Check:
1. whether every factual claim is supported;
2. whether the text contains advertising or evaluative language;
3. whether the style is neutral and factual;
4. whether the stated industry and geography agree with the fields;
5. whether employee and financial statements match the supplied values;
6. whether the case should be accepted or sent to manual review.

Return the decision and a concise list of issues. Do not introduce new facts.
```

## 6. Transparency note

The repository separates:

- prompts preserved directly in source code;
- reconstructed documentation templates;
- deterministic validation and routing rules.

This distinction should be maintained in the paper and supplementary materials.
