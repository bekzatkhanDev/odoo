BEGIN;

INSERT INTO branches (branch_code, branch_name, city, address, phone) VALUES
('BR-001','Central Pharmacy','Almaty','Abay Ave 10','+7 727 111-11-11'),
('BR-002','East Pharmacy','Almaty','Dostyk 25','+7 727 222-22-22'),
('BR-003','Astana Branch','Astana','Mangilik El 5','+7 717 333-33-33');

INSERT INTO categories (category_name, description) VALUES
('Antibiotics','Antibacterial drugs'),('Analgesics','Pain relievers'),('Vitamins','Vitamin supplements'),
('Antihistamines','Allergy relief'),('Cardiovascular','Heart & blood pressure');

INSERT INTO manufacturers (manufacturer_name, country) VALUES
('PharmaCorp','Germany'),('MediLife','India'),('HealthPlus','USA');

INSERT INTO suppliers (supplier_name, business_id, phone, email, address) VALUES
('MedSupply LLC','1234567890','+7 701 100-00-00','med@supply.kz','Almaty'),
('Global Pharma','0987654321','+7 702 200-00-00','global@pharma.kz','Astana');

INSERT INTO roles (role_name, description) VALUES
('Pharmacist','Licensed pharmacist'),('Cashier','Sales cashier'),('Manager','Branch manager');

INSERT INTO employees (branch_id, role_id, first_name, last_name, email, phone, hire_date) VALUES
(1,1,'Aruzhan','Sadykova','aruzhan@densamed.kz','+7 701 1','2023-01-15'),
(1,2,'Dias','Nurlanov','dias@densamed.kz','+7 701 2','2023-03-10'),
(2,1,'Madina','Kenzhe','madina@densamed.kz','+7 702 1','2023-02-20'),
(3,3,'Timur','Bekov','timur@densamed.kz','+7 717 1','2022-11-01');

INSERT INTO warehouses (branch_id, warehouse_name, location_description) VALUES
(1,'Main Warehouse','Back storage'),(2,'Main Warehouse','Back storage'),(3,'Main Warehouse','Back storage');

INSERT INTO medicines (barcode, trade_name, generic_name, category_id, manufacturer_id, dosage_form, strength, retail_price, requires_prescription, min_stock) VALUES
('1000000000001','Amoxicillin 500','Amoxicillin',1,1,'capsule','500mg',1200,true,20),
('1000000000002','Ibuprofen 200','Ibuprofen',2,2,'tablet','200mg',800,false,30),
('1000000000003','Paracetamol 500','Paracetamol',2,2,'tablet','500mg',600,false,40),
('1000000000004','Vitamin C 1000','Ascorbic Acid',3,3,'tablet','1000mg',1500,false,15),
('1000000000005','Loratadine 10','Loratadine',4,1,'tablet','10mg',900,false,25),
('1000000000006','Captopril 25','Captopril',5,1,'tablet','25mg',1100,true,10),
('1000000000007','Azithromycin 250','Azithromycin',1,2,'tablet','250mg',2200,true,10),
('1000000000008','Diclofenac Gel','Diclofenac',2,3,'gel','1%',1800,false,12),
('1000000000009','Vitamin D3 2000','Cholecalciferol',3,3,'capsule','2000IU',2000,false,15),
('1000000000010','Cetirizine 10','Cetirizine',4,2,'tablet','10mg',750,false,20),
('1000000000011','Amlodipine 5','Amlodipine',5,1,'tablet','5mg',1300,true,10),
('1000000000012','Amoxiclav 625','Amoxicillin+Clavulanate',1,1,'tablet','625mg',2600,true,8),
('1000000000013','Nurofen 400','Ibuprofen',2,2,'tablet','400mg',1400,false,20),
('1000000000014','Multivitamin','Multivitamin',3,3,'capsule','complex',2500,false,10),
('1000000000015','Zyrtec 10','Cetirizine',4,2,'tablet','10mg',1600,false,15),
('1000000000016','Enalapril 10','Enalapril',5,1,'tablet','10mg',950,true,12),
('1000000000017','Doxycycline 100','Doxycycline',1,2,'capsule','100mg',1700,true,10),
('1000000000018','Aspirin 100','Acetylsalicylic acid',2,3,'tablet','100mg',500,false,30),
('1000000000019','Omega-3 1000','Fish oil',3,3,'capsule','1000mg',2800,false,8),
('1000000000020','Fexofenadine 120','Fexofenadine',4,1,'tablet','120mg',2100,false,12);

COMMIT;
