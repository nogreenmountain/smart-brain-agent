processors:
  resource:
    attributes:
      - key: ProjectId
        action: upsert
        from_context: auth.project_id
      - key: {{ SEMCONV.AGENTOPS_PROJECT_ID }}
        action: upsert
        from_context: auth.project_id
      - key: agentops.employee.id
        action: upsert
        from_context: auth.employee_id
      - key: agentops.employee.name
        action: upsert
        from_context: auth.employee_name
      - key: agentops.ingest.kind
        action: upsert
        from_context: auth.ingest_kind

  resourcedetection/system:
    detectors: ['system']
    system:
      hostname_sources: ['os']

  filter/workday_cli_logs:
    error_mode: ignore
    logs:
      log_record:
        - resource.attributes["agentops.ingest.kind"] == "workday_cli"

  transform/workday_privacy:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          - set(span.attributes["agentops.employee.id"],
              resource.attributes["agentops.employee.id"])
              where resource.attributes["agentops.ingest.kind"] == "workday_cli"
          - set(span.attributes["agentops.employee.name"],
              resource.attributes["agentops.employee.name"])
              where resource.attributes["agentops.ingest.kind"] == "workday_cli"
          - delete_key(resource.attributes, "user.email")
          - delete_key(resource.attributes, "user.account_id")
          - delete_key(span.attributes, "user.email")
          - delete_key(span.attributes, "user.account_id")
          - delete_key(span.attributes, "user_prompt")
          - delete_key(span.attributes, "assistant_response")
          - delete_key(span.attributes, "prompt")
          - delete_key(span.attributes, "response")
          - delete_key(span.attributes, "tool_input")
          - delete_key(span.attributes, "tool_output")
          - delete_key(span.attributes, "tool.input")
          - delete_key(span.attributes, "tool.output")
          - delete_key(span.attributes, "tool_parameters")
          - delete_key(span.attributes, "full_command")
          - delete_key(span.attributes, "file_path")
          - delete_key(span.attributes, "body")
          - delete_key(span.attributes, "body_ref")
          - delete_key(span.attributes, "request_body")
          - delete_key(span.attributes, "response_body")
          - delete_key(span.attributes, "error")
      - context: spanevent
        statements:
          - delete_key(resource.attributes, "user.email")
          - delete_key(resource.attributes, "user.account_id")
          - delete_key(spanevent.attributes, "user.email")
          - delete_key(spanevent.attributes, "user.account_id")
          - delete_key(spanevent.attributes, "user_prompt")
          - delete_key(spanevent.attributes, "assistant_response")
          - delete_key(spanevent.attributes, "prompt")
          - delete_key(spanevent.attributes, "response")
          - delete_key(spanevent.attributes, "tool_input")
          - delete_key(spanevent.attributes, "tool_output")
          - delete_key(spanevent.attributes, "tool.input")
          - delete_key(spanevent.attributes, "tool.output")
          - delete_key(spanevent.attributes, "tool_parameters")
          - delete_key(spanevent.attributes, "full_command")
          - delete_key(spanevent.attributes, "file_path")
          - delete_key(spanevent.attributes, "body")
          - delete_key(spanevent.attributes, "body_ref")
          - delete_key(spanevent.attributes, "request_body")
          - delete_key(spanevent.attributes, "response_body")
          - delete_key(spanevent.attributes, "error")

  transform:
    trace_statements:
      # we are using root-level trace_statements so that the cache is shared across
      # all transforms in the pipeline (as opposed to `- scope: span` which creates
      # a new cache for each transform)

      # cost data gets populated dynamically on container build
      {% for cost in MODEL_COSTS %}
      - set( span.cache["_input_costs"]["{{ cost.model }}"], {{ cost.input }})
      - set(span.cache["_output_costs"]["{{ cost.model }}"], {{ cost.output }})
      {% endfor %}

      # set prompt cost on spans that have prompt tokens an a known model
      - set(span.attributes["{{ SEMCONV.LLM_USAGE_PROMPT_COST }}"],
          Double(span.attributes["{{ SEMCONV.LLM_USAGE_PROMPT_TOKENS }}"]) *
          span.cache["_input_costs"][span.attributes["{{ SEMCONV.LLM_RESPONSE_MODEL }}"]])
          where (
            span.attributes["{{ SEMCONV.LLM_USAGE_PROMPT_TOKENS }}"] != nil and
            span.attributes["{{ SEMCONV.LLM_RESPONSE_MODEL }}"] != nil and
            span.cache["_input_costs"][span.attributes["{{ SEMCONV.LLM_RESPONSE_MODEL }}"]] != nil)

      # set completion cost on spans that have completion tokens an a known model
      - set(span.attributes["{{ SEMCONV.LLM_USAGE_COMPLETION_COST }}"],
          Double(span.attributes["{{ SEMCONV.LLM_USAGE_COMPLETION_TOKENS }}"]) *
          span.cache["_output_costs"][span.attributes["{{ SEMCONV.LLM_RESPONSE_MODEL }}"]])
          where (
            span.attributes["{{ SEMCONV.LLM_USAGE_COMPLETION_TOKENS }}"] != nil and
            span.attributes["{{ SEMCONV.LLM_RESPONSE_MODEL }}"] != nil and
            span.cache["_output_costs"][span.attributes["{{ SEMCONV.LLM_RESPONSE_MODEL }}"]] != nil)
