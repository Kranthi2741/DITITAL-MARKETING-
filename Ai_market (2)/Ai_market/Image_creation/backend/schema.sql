CREATE DATABASE IF NOT EXISTS marketai;
USE marketai;

CREATE TABLE IF NOT EXISTS users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,          -- bcrypt hash
    role        ENUM('admin','user') NOT NULL DEFAULT 'user',
    must_change  TINYINT(1) NOT NULL DEFAULT 1, -- 1 = force password setup on first login
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Default admin account  (password: Admin@MarketAI1)
-- Hash generated with bcrypt rounds=12
INSERT IGNORE INTO users (email, password, role, must_change)
VALUES (
    'admin@marketai.com',
    '$2b$12$KIX4V7Q1z3Yw5N8mP2oXOeW6LhRtJdCvBnMsAqFgHuYpZeT0iDlK2',
    'admin',
    0
);
