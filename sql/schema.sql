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
