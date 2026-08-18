BEGIN;

ALTER TABLE public.documents
    DROP CONSTRAINT IF EXISTS documents_format_check;

ALTER TABLE public.documents
    ADD CONSTRAINT documents_format_check CHECK (
        format IN (
            'bat', 'c', 'conf', 'cpp', 'cs', 'css', 'csv', 'docx', 'go',
            'h', 'hpp', 'html', 'java', 'js', 'json', 'jsx', 'log', 'md',
            'pdf', 'pptx', 'ps1', 'py', 'rs', 'scss', 'sh', 'sql', 'ts',
            'tsx', 'txt', 'vue', 'xlsx', 'xml', 'yaml', 'yml'
        )
    );

ALTER TABLE public.project_memory_draft_sources
    DROP CONSTRAINT IF EXISTS project_memory_draft_sources_format_check;

ALTER TABLE public.project_memory_draft_sources
    ADD CONSTRAINT project_memory_draft_sources_format_check CHECK (
        format IN (
            'bat', 'c', 'conf', 'cpp', 'cs', 'css', 'csv', 'docx', 'go',
            'h', 'hpp', 'html', 'java', 'js', 'json', 'jsx', 'log', 'md',
            'pdf', 'pptx', 'ps1', 'py', 'rs', 'scss', 'sh', 'sql', 'ts',
            'tsx', 'txt', 'vue', 'xlsx', 'xml', 'yaml', 'yml'
        )
    );

COMMIT;
