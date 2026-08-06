BEGIN;

WITH latest_mcp_attribution AS (
    SELECT DISTINCT ON (c.page_id)
           c.page_id,
           r.triggered_by_user_id
    FROM public.project_wiki_changes c
    JOIN public.project_wiki_compile_runs r ON r.id = c.run_id
    WHERE c.reason_code = 'mcp_proposal'
      AND c.status = 'applied'
      AND c.page_id IS NOT NULL
      AND r.triggered_by_user_id IS NOT NULL
    ORDER BY c.page_id, c.reviewed_at DESC NULLS LAST, c.created_at DESC
)
UPDATE public.project_wiki_pages p
SET created_by_user_id = attribution.triggered_by_user_id
FROM latest_mcp_attribution attribution
WHERE p.id = attribution.page_id;

WITH latest_mcp_attribution AS (
    SELECT DISTINCT ON (c.page_id)
           c.page_id,
           r.triggered_by_user_id
    FROM public.project_wiki_changes c
    JOIN public.project_wiki_compile_runs r ON r.id = c.run_id
    WHERE c.reason_code = 'mcp_proposal'
      AND c.status = 'applied'
      AND c.page_id IS NOT NULL
      AND r.triggered_by_user_id IS NOT NULL
    ORDER BY c.page_id, c.reviewed_at DESC NULLS LAST, c.created_at DESC
)
UPDATE public.project_wiki_page_versions v
SET created_by_user_id = attribution.triggered_by_user_id
FROM latest_mcp_attribution attribution
JOIN public.project_wiki_pages p ON p.id = attribution.page_id
WHERE v.page_id = attribution.page_id
  AND v.version = p.current_version;

WITH latest_mcp_attribution AS (
    SELECT DISTINCT ON (c.page_id)
           c.page_id,
           r.triggered_by_user_id
    FROM public.project_wiki_changes c
    JOIN public.project_wiki_compile_runs r ON r.id = c.run_id
    WHERE c.reason_code = 'mcp_proposal'
      AND c.status = 'applied'
      AND c.page_id IS NOT NULL
      AND r.triggered_by_user_id IS NOT NULL
    ORDER BY c.page_id, c.reviewed_at DESC NULLS LAST, c.created_at DESC
)
UPDATE public.documents d
SET created_by_user_id = attribution.triggered_by_user_id
FROM latest_mcp_attribution attribution
JOIN public.project_wiki_pages p ON p.id = attribution.page_id
WHERE d.id = p.document_id;

COMMIT;
