CREATE TABLE IF NOT EXISTS music_job_lyrics (
    job_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    status VARCHAR(16) NOT NULL,
    claim_token VARCHAR(32) NULL,
    lease_until BIGINT NOT NULL DEFAULT 0,
    payload_json LONGTEXT NULL,
    CONSTRAINT fk_music_lyrics_job FOREIGN KEY (job_id) REFERENCES music_jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
