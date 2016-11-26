CREATE DATABASE seocrawler;
CREATE USER 'seo'@'localhost' IDENTIFIED BY 'oes';
GRANT ALL PRIVILEGES ON seocrawler . * TO 'seo'@'localhost';
FLUSH PRIVILEGES;
