-- ============================================================
-- TracePic 스키마 (MySQL 8.0, utf8mb4)
-- 출처: 개발 DB(devDB) SHOW CREATE TABLE 결과 그대로 (2026-11-13, 2026-11-17 인덱스·외래키 반영)
-- 주의: devDB는 다른 서비스와 공용 DB입니다. tracepic_* 테이블만 다룹니다.
-- 사용: mysql -h <host> -u <user> -p <db> < sql/schema.sql
-- ============================================================

SET NAMES utf8mb4;

-- ------------------------------------------------------------
-- tracepic_photos: 사진 메타데이터 + GPS (pic_id 기준, 이미지 파일은 암호화되어 STORAGE_DIR에 저장)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `tracepic_photos` (
  `pic_id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '사진파일 고유 식별자',
  `user_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '사용자ID',
  `base_dt` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '촤열 시간 의 년월일',
  `original_file_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '업로드된 원본 파일명',
  `file_path` varchar(512) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '사진 파일이 저장된 서버 경로 또는 URL',
  `photo_at` datetime NOT NULL COMMENT '촬영 시간 타임스탬프',
  `latitude` decimal(10,7) DEFAULT '0.0000000' COMMENT '위도 (Latitude, Y좌표)',
  `longitude` decimal(11,7) DEFAULT '0.0000000' COMMENT '경도 (Longitude, X좌표)',
  `status` varchar(1) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'A' COMMENT 'a:완전공유 , b:부분공유 , c:나만, d:삭제, z:완전삭제',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'DB 저장 시각',
  PRIMARY KEY (`pic_id`),
  KEY `tracepic_photos_inx01` (`base_dt`,`user_id`) USING BTREE,
  -- 2026-11-17 추가: 사용자별 기간 조회(WHERE user_id = ? AND base_dt BETWEEN ...)용. 등호 조건 컬럼을 앞에 둔다
  KEY `tracepic_photos_inx02` (`user_id`,`base_dt`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='사진 메타데이터 및 GPS 정보 테이블';

-- 이미 만들어진 DB 에 인덱스만 추가할 때 (온라인 DDL, 잠금 없음):
-- ALTER TABLE tracepic_photos ADD INDEX tracepic_photos_inx02 (user_id, base_dt), ALGORITHM=INPLACE, LOCK=NONE;

-- ------------------------------------------------------------
-- tracepic_notes: 사진별 마크다운 기록 (pic_id → tracepic_photos)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `tracepic_notes` (
  `note_id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '문서 고유 식별자',
  `pic_id` bigint unsigned NOT NULL COMMENT '사진 고유 식별자',
  `title` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '제목',
  `note` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'md 문서',
  `use_yn` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT 'Y' COMMENT 'y:사용 , n: 미사용',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'DB 최초 저장 시각',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'DB 최후 저장 시각',
  PRIMARY KEY (`note_id`),
  KEY `tracepic_notes_tracepic_photos_FK` (`pic_id`),
  CONSTRAINT `tracepic_notes_tracepic_photos_FK` FOREIGN KEY (`pic_id`) REFERENCES `tracepic_photos` (`pic_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='사진의 MD문서';

-- ------------------------------------------------------------
-- tracepic_daily: 일별 요약 마크다운 기록 (base_dt + user_id)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `tracepic_daily` (
  `daily_id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '일별 고유 식별자',
  `base_dt` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '년월일',
  `user_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '사용자ID',
  `title` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '제목',
  `note` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'md 문서',
  `use_yn` varchar(1) COLLATE utf8mb4_unicode_ci DEFAULT 'Y' COMMENT 'y:사용 , n: 미사용',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'DB 최초 저장 시각',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'DB 최후 저장 시각',
  PRIMARY KEY (`daily_id`),
  KEY `tracepic_photos_inx01` (`base_dt`,`user_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='일별 요약 MD문서';

-- ------------------------------------------------------------
-- tracepic_signup: 메일 가입 신청 (2026-11-20 사용자 확인 후 추가)
--   메일 인증(V → P) → 관리자 승인(A) 순간에만 user_info 에 INSERT (user_id = email). 거절은 R.
--   승인 전 신청자는 공유 테이블 user_info 에 없으므로 다른 서비스에 보이지 않는다.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `tracepic_signup` (
  `signup_id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '가입 신청 고유 식별자',
  `email` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '가입 메일 (승인 시 user_id 로 사용)',
  `password` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'bcrypt 해시',
  `status` varchar(1) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'V' COMMENT 'V:메일인증대기 P:승인대기 A:승인 R:거절',
  `verified_at` datetime DEFAULT NULL COMMENT '메일 인증 시각',
  `decided_at` datetime DEFAULT NULL COMMENT '승인·거절 시각',
  `decided_by` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '승인·거절한 관리자 user_id',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '신청 시각',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '최후 변경 시각',
  PRIMARY KEY (`signup_id`),
  KEY `tracepic_signup_inx01` (`email`),
  KEY `tracepic_signup_inx02` (`status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='메일 가입 신청';

-- ------------------------------------------------------------
-- tracepic_email_codes: 메일 인증 코드 (가입 S / 비밀번호 재설정 R) (2026-11-20 사용자 확인 후 추가)
--   코드는 평문으로 저장하지 않고 HMAC-SHA256(SECRET_KEY) 값만 둔다. 10분 유효, 5회 틀리면 무효.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `tracepic_email_codes` (
  `code_id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '인증 코드 고유 식별자',
  `purpose` varchar(1) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'S:가입 R:비밀번호재설정',
  `email` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '받는 메일',
  `code_hash` char(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'HMAC-SHA256(코드)',
  `attempts` tinyint unsigned NOT NULL DEFAULT '0' COMMENT '틀린 횟수',
  `expires_at` datetime NOT NULL COMMENT '만료 시각',
  `used_at` datetime DEFAULT NULL COMMENT '사용(인증 성공) 시각',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '발급 시각',
  PRIMARY KEY (`code_id`),
  KEY `tracepic_email_codes_inx01` (`email`, `purpose`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='메일 인증 코드';
