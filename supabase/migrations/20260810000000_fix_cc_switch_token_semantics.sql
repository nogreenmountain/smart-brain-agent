BEGIN;

UPDATE public.cc_switch_usage_daily
SET total_tokens =
        CASE
            WHEN input_token_semantics = 2 THEN input_tokens
            WHEN app_type IN ('codex', 'gemini')
                 AND input_token_semantics = 1
                 AND input_tokens >= cache_read_tokens + cache_creation_tokens
            THEN input_tokens - cache_read_tokens - cache_creation_tokens
            WHEN app_type IN ('codex', 'gemini')
                 AND input_token_semantics = 0
                 AND input_tokens >= cache_read_tokens
            THEN input_tokens - cache_read_tokens
            ELSE input_tokens
        END
        + output_tokens
        + cache_read_tokens
        + cache_creation_tokens,
    updated_at = now();

UPDATE public.cc_switch_usage_sync_status AS status
SET total_tokens = COALESCE((
        SELECT sum(usage.total_tokens)
        FROM public.cc_switch_usage_daily AS usage
        WHERE usage.user_id = status.user_id
          AND usage.device_id = status.device_id
          AND usage.usage_date >= status.range_start
          AND usage.usage_date <= status.range_end
    ), 0),
    updated_at = now()
WHERE status.status = 'ok';

COMMIT;
