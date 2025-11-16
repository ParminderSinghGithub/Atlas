package db

import (
  "gorm.io/driver/postgres"
  "gorm.io/gorm"
  "os"
)

func Connect() (*gorm.DB, error) {
  dsn := os.Getenv("POSTGRES_URI")
  db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
  return db, err
}
