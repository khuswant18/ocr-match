CREATE TABLE poh_invs (
  id int UNSIGNED NOT NULL,
  po_number varchar(255) DEFAULT NULL,
  poh_schedule_id int UNSIGNED DEFAULT NULL,
  vendor_invoice_number varchar(255) DEFAULT NULL,
  invoice_document varchar(255) DEFAULT NULL,
  unique_document_name varchar(255) DEFAULT '',
  invoice_task_status enum('pending','approved','rejected','resubmitted') NOT NULL DEFAULT 'pending',
  vendor_invoice_id int UNSIGNED DEFAULT NULL,
  remarks json DEFAULT NULL,
  vendor_invoice_date datetime DEFAULT NULL,
  created_by int UNSIGNED DEFAULT NULL,
  updated_by int UNSIGNED DEFAULT NULL,
  created_at datetime DEFAULT NULL,
  updated_at datetime DEFAULT NULL,
  po_number_bigint bigint UNSIGNED GENERATED ALWAYS AS (cast(po_number as unsigned)) STORED
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE poh_invs
  ADD PRIMARY KEY (id),
  ADD KEY poh_schedule_id (poh_schedule_id),
  ADD KEY created_by (created_by),
  ADD KEY updated_by (updated_by),
  ADD KEY idx_phi_po (po_number),
  ADD KEY idx_poh_invs_po_number (po_number),
  ADD KEY idx_poh_invs_po_number_bigint (po_number_bigint);


ALTER TABLE poh_invs
  MODIFY id int UNSIGNED NOT NULL AUTO_INCREMENT; 
/*
-- Query: Select id, po_number, poh_schedule_id, vendor_invoice_number, invoice_document, unique_document_name, invoice_task_status, vendor_invoice_id, remarks, vendor_invoice_date, created_by, updated_by, created_at, updated_at from poh_invs WHERE po_number IN (3969397, 3975366, 4010510, 4013368, 4014862, 4016684, 4016852, 4017234, 4017241, 4017246)
LIMIT 0, 5000

-- Date: 2026-03-20 18:23
*/
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (18902,'4010510',32250,NULL,NULL,'','pending',NULL,'[{\"type\": \"vendor\", \"userId\": 1217, \"message\": \"LADLAD\", \"user_name\": \"VIRGINIA  AND GODSPEED\", \"created_at\": \"2025-11-04T08:44:59.575Z\"}]',NULL,1217,NULL,'2025-11-04 08:44:59','2025-11-04 08:44:59');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (18915,'3975366',32145,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-04 09:10:49','2025-11-04 09:10:49');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (18918,'3969397',32144,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-04 09:12:39','2025-11-04 09:12:39');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (18934,'4014862',32112,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-04 13:09:16','2025-11-04 13:09:16');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (18944,'4016852',32127,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-05 01:55:49','2025-11-05 01:55:49');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (18993,'4013368',32463,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-05 08:37:49','2025-11-05 08:37:49');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (19000,'4017241',32570,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-05 11:53:23','2025-11-05 11:53:23');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (19002,'4017246',32569,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-05 12:07:42','2025-11-05 12:07:42');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (19117,'4017234',32068,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-06 10:19:12','2025-11-06 10:19:12');
INSERT INTO `poh_invs` (`id`,`po_number`,`poh_schedule_id`,`vendor_invoice_number`,`invoice_document`,`unique_document_name`,`invoice_task_status`,`vendor_invoice_id`,`remarks`,`vendor_invoice_date`,`created_by`,`updated_by`,`created_at`,`updated_at`) VALUES (19969,'4016684',35172,NULL,NULL,'','pending',NULL,'[]',NULL,1217,NULL,'2025-11-12 10:13:40','2025-11-12 10:13:40');
