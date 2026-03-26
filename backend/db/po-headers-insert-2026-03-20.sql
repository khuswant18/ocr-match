CREATE TABLE po_headers (
  po_number varchar(20) NOT NULL,
  po_date date NOT NULL,
  store_code varchar(20) DEFAULT NULL,
  supplier_code int DEFAULT NULL,
  po_status varchar(10) DEFAULT NULL COMMENT '3-released, 9-cancelled',
  po_acknowledge_status varchar(10) DEFAULT NULL COMMENT '1-new, 2-confirmed',
  po_acknowledge_at datetime DEFAULT NULL,
  is_schedule_approved tinyint(1) NOT NULL DEFAULT '0',
  buyer_code varchar(65) DEFAULT NULL,
  term_code int DEFAULT NULL,
  po_expected_delivery_date date DEFAULT NULL,
  po_cancel_date date DEFAULT NULL,
  po_notes1 text, 
  po_notes2 text,
  po_notes3 text,
  po_freight_allowed int DEFAULT NULL,
  po_department varchar(50) DEFAULT NULL,
  po_sub_department varchar(50) DEFAULT NULL,
  po_receiver_no varchar(20) DEFAULT NULL,
  po_received_date date DEFAULT NULL,
  po_contact varchar(50) DEFAULT NULL,
  po_currency varchar(50) DEFAULT NULL,
  po_point varchar(50) DEFAULT NULL,
  po_level_discount varchar(255) DEFAULT NULL,
  poh_attr json DEFAULT NULL,
  release_date datetime DEFAULT NULL,
  po_ship_comment text,
  po_level_sku_discount float DEFAULT '0',
  po_net_value float DEFAULT '0',
  po_tot_val_at_cp float DEFAULT '0',
  po_tot_val_at_sp float DEFAULT '0',
  po_tot_discount_val float DEFAULT '0',
  po_ship_via1 text NOT NULL,
  po_ship_via2 text NOT NULL,
  po_fob text NOT NULL,
  freight_allowance_id int UNSIGNED DEFAULT NULL,
  created_at datetime DEFAULT NULL,
  updated_at datetime DEFAULT NULL,
  po_number_bigint bigint UNSIGNED GENERATED ALWAYS AS (cast(po_number as unsigned)) STORED,
  sku_counts int NOT NULL DEFAULT '0'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


ALTER TABLE po_headers
  ADD PRIMARY KEY (po_number),
  ADD KEY freight_allowance_id (freight_allowance_id),
  ADD KEY idx_po_status_ack_po (po_status,po_acknowledge_status,po_number),
  ADD KEY idx_status_ack_updated (po_status,po_acknowledge_status,updated_at DESC,po_number),
  ADD KEY idx_po_status_ack_number (po_status,po_acknowledge_status,po_number),
  ADD KEY idx_po_headers_status_created (po_status,created_at),
  ADD KEY idx_po_headers_created_at_desc (created_at),
  ADD KEY idx_po_headers_supplier_status (supplier_code,po_status),
  ADD KEY idx_po_headers_supplier_status_bigint (supplier_code,po_status,created_at DESC),
  ADD KEY idx_po_headers_po_number_bigint (po_number_bigint),
  ADD KEY idx_po_headers_sku_counts (sku_counts);




/*
-- Query: select po_number, po_date, store_code, supplier_code, po_status, po_acknowledge_status, po_acknowledge_at, is_schedule_approved, buyer_code, term_code, po_expected_delivery_date, po_cancel_date, po_notes1, po_notes2, po_notes3, po_freight_allowed, po_department, po_sub_department, po_receiver_no, po_received_date, po_contact, po_currency, po_point, po_level_discount, poh_attr, release_date, po_ship_comment, po_level_sku_discount, po_net_value, po_tot_val_at_cp, po_tot_val_at_sp, po_tot_discount_val, po_ship_via1, po_ship_via2, po_fob, freight_allowance_id, created_at, updated_at, sku_counts from po_headers WHERE po_number IN (3969397, 3975366, 4010510, 4013368, 4014862, 4016684, 4016852, 4017234, 4017241, 4017246)
LIMIT 0, 5000

-- Date: 2026-03-20 18:17
*/
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('3969397','2025-11-03','15001',3839,'3','2','2025-11-03 05:50:46',1,'JOC',211,'2025-11-09','2025-11-15',NULL,'SUPPLIER SO',NULL,1,'630',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-11-03 00:00:00','                    ',0,166010,169398,212800,0,'                    ','                    ','DESTINATION         ',1,'2025-11-03 03:17:14','2025-11-03 09:38:18',45);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('3975366','2025-11-03','15001',3839,'3','2','2025-11-03 05:50:46',1,'JOC',211,'2025-11-09','2025-11-15',NULL,'SUPPLIER SO',NULL,1,'630',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-11-03 00:00:00','                    ',0,40938.8,45487.5,54078,0,'                    ','                    ','DESTINATION         ',1,'2025-11-03 03:17:14','2025-11-03 09:35:41',11);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('4010510','2025-11-03','15008',3839,'3','2','2025-11-03 08:39:20',1,'RML',211,'2025-11-09','2025-11-30','S.O 21750 LADLAD',NULL,NULL,1,'630',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-11-03 00:00:00','                    ',0,31294.3,34771.4,40418,0,'                    ','                    ','DESTINATION         ',1,'2025-11-03 08:16:39','2025-11-04 03:01:20',10);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('4013368','2025-10-28','18004',3839,'3','2','2025-11-04 04:54:34',1,'CAB',211,'2025-11-03','2025-12-09',NULL,NULL,NULL,1,'630',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-10-28 00:00:00','                    ',0,37658.3,38426.9,48610.8,0,'                    ','                    ','DESTINATION         ',1,'2025-10-28 04:16:49','2025-11-04 10:28:56',16);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('4014862','2025-10-29','13006',3839,'3','2','2025-10-30 08:31:04',1,'JMO',211,'2025-11-04','2025-11-10',NULL,'SO BY SUPPLIER',NULL,1,'630',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-10-29 00:00:00','                    ',0,97244,99228.5,125632,0,'                    ','                    ','DESTINATION         ',1,'2025-10-29 06:16:59','2025-11-04 02:19:35',21);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('4016684','2025-10-30','18007',3839,'3','2','2025-11-04 02:52:16',1,'JOC',211,'2025-11-05','2025-11-30',NULL,'OCT. NPI',NULL,1,'600',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-10-30 00:00:00','                    ',0,2600,2600,2912,0,'                    ','                    ','DESTINATION         ',1,'2025-10-30 09:16:34','2025-11-11 06:09:49',1);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('4016852','2025-10-30','18001',3839,'3','2','2025-11-03 05:19:48',1,'JOC',211,'2025-11-05','2025-11-30',NULL,'OCT. NPI',NULL,1,'600',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-10-30 00:00:00','                    ',0,2600,2600,2912,0,'                    ','                    ','DESTINATION         ',1,'2025-10-31 00:16:20','2025-11-05 01:33:55',1);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('4017234','2025-11-03','17002',3839,'3','2','2025-11-03 03:07:44',1,'MPR',211,'2025-11-10','2025-11-30','POTOTAN',NULL,'ARS363291680',1,'600',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-11-03 00:00:00','                    ',0,6986.65,7504.46,8509.8,0,'                    ','                    ','DESTINATION         ',1,'2025-11-03 02:16:59','2025-11-04 01:45:04',2);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('4017241','2025-11-03','18002',3839,'3','2','2025-11-04 06:35:13',1,'JSC',211,'2025-11-10','2025-11-15','OPOL',NULL,'ARS363291679',1,'600',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-11-03 00:00:00','                    ',0,3576.04,3841.07,4360.8,0,'                    ','                    ','DESTINATION         ',1,'2025-11-03 02:16:59','2025-11-05 00:40:07',2);
INSERT INTO `po_headers` (`po_number`,`po_date`,`store_code`,`supplier_code`,`po_status`,`po_acknowledge_status`,`po_acknowledge_at`,`is_schedule_approved`,`buyer_code`,`term_code`,`po_expected_delivery_date`,`po_cancel_date`,`po_notes1`,`po_notes2`,`po_notes3`,`po_freight_allowed`,`po_department`,`po_sub_department`,`po_receiver_no`,`po_received_date`,`po_contact`,`po_currency`,`po_point`,`po_level_discount`,`poh_attr`,`release_date`,`po_ship_comment`,`po_level_sku_discount`,`po_net_value`,`po_tot_val_at_cp`,`po_tot_val_at_sp`,`po_tot_discount_val`,`po_ship_via1`,`po_ship_via2`,`po_fob`,`freight_allowance_id`,`created_at`,`updated_at`,`sku_counts`) VALUES ('4017246','2025-11-03','18005',3839,'3','2','2025-11-04 06:34:57',1,'JSC',211,'2025-11-10','2025-11-15','BALINGASAG',NULL,'ARS363291706',1,'600',NULL,' ','1900-01-01','CARL CORTES         ',NULL,'                    ',NULL,NULL,'2025-11-03 00:00:00','                    ',0,4925.16,5290.18,5880,0,'                    ','                    ','DESTINATION         ',1,'2025-11-03 02:16:59','2025-11-04 08:17:01',2);
