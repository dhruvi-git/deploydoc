variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "asia-south1" # Mumbai
}
variable "image" { type = string }
variable "app_version" {
  type    = string
  default = "dev"
}
variable "container_port" {
  type    = number
  default = 8080
}
variable "cpu" {
  type    = string
  default = "1"
}
variable "memory" {
  type    = string
  default = "512Mi"
}
variable "database_url" {
  type    = string
  default = ""
}
