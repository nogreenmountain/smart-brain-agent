BEGIN;

CREATE TABLE IF NOT EXISTS public.project_material_documents (
    document_id uuid PRIMARY KEY REFERENCES public.documents(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    draft_id uuid REFERENCES public.project_memory_drafts(id) ON DELETE SET NULL,
    uploaded_by_user_id uuid,
    uploaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_material_documents_project
    ON public.project_material_documents (project_id, uploaded_at DESC);

CREATE INDEX IF NOT EXISTS idx_project_material_documents_draft
    ON public.project_material_documents (draft_id);

INSERT INTO public.project_material_documents (
    document_id, project_id, draft_id, uploaded_by_user_id, uploaded_at
)
SELECT d.id, d.project_id, d.memory_draft_id, d.created_by_user_id, d.created_at
FROM public.documents d
WHERE COALESCE(d.memory_type, 'raw_project_material') != 'project_long_term_memory'
ON CONFLICT (document_id) DO NOTHING;

COMMIT;
