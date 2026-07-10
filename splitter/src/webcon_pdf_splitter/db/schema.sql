CREATE TABLE dbo.document_type (
    document_type_id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_document_type PRIMARY KEY,
    name NVARCHAR(200) NOT NULL,
    is_active BIT NOT NULL CONSTRAINT DF_document_type_is_active DEFAULT (1),
    auto_accept_threshold DECIMAL(5,4) NOT NULL CONSTRAINT DF_document_type_threshold DEFAULT (0.9000),
    target_workflow NVARCHAR(200) NULL,
    target_attachment_category NVARCHAR(200) NULL,
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_document_type_created_at DEFAULT (SYSUTCDATETIME()),
    updated_at DATETIME2(0) NOT NULL CONSTRAINT DF_document_type_updated_at DEFAULT (SYSUTCDATETIME())
);

CREATE TABLE dbo.document_pattern (
    document_pattern_id INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_document_pattern PRIMARY KEY,
    document_type_id INT NOT NULL CONSTRAINT FK_document_pattern_type REFERENCES dbo.document_type(document_type_id),
    header NVARCHAR(500) NOT NULL,
    phrases_json NVARCHAR(MAX) NOT NULL CONSTRAINT DF_document_pattern_phrases DEFAULT (N'[]'),
    excluded_phrases_json NVARCHAR(MAX) NOT NULL CONSTRAINT DF_document_pattern_excluded DEFAULT (N'[]'),
    weight DECIMAL(8,4) NOT NULL CONSTRAINT DF_document_pattern_weight DEFAULT (1.0000),
    source NVARCHAR(50) NOT NULL,
    is_active BIT NOT NULL CONSTRAINT DF_document_pattern_is_active DEFAULT (1),
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_document_pattern_created_at DEFAULT (SYSUTCDATETIME())
);

CREATE TABLE dbo.splitter_job (
    splitter_job_id UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_splitter_job PRIMARY KEY,
    webcon_element_id INT NULL,
    source_file_name NVARCHAR(500) NOT NULL,
    status NVARCHAR(50) NOT NULL,
    page_count INT NULL,
    detected_document_count INT NULL,
    technical_error NVARCHAR(2000) NULL,
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_splitter_job_created_at DEFAULT (SYSUTCDATETIME()),
    finished_at DATETIME2(0) NULL
);

CREATE TABLE dbo.classification_feedback (
    classification_feedback_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_classification_feedback PRIMARY KEY,
    splitter_job_id UNIQUEIDENTIFIER NULL CONSTRAINT FK_feedback_job REFERENCES dbo.splitter_job(splitter_job_id),
    webcon_package_element_id INT NULL,
    page_number INT NOT NULL,
    system_document_type NVARCHAR(200) NULL,
    operator_document_type NVARCHAR(200) NULL,
    system_is_first_page BIT NULL,
    operator_is_first_page BIT NULL,
    operator_login NVARCHAR(200) NULL,
    used_for_pattern_update BIT NOT NULL CONSTRAINT DF_feedback_used DEFAULT (0),
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_feedback_created_at DEFAULT (SYSUTCDATETIME())
);
