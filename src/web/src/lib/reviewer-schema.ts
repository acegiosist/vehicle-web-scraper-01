import { z } from "zod";

export const REVIEWER_COOKIE = "kb_reviewer";

export const reviewerSchema = z
  .string()
  .trim()
  .min(2, "Escribe tu nombre (mínimo 2 caracteres).")
  .max(60, "Máximo 60 caracteres.")
  .regex(/^[\p{L}\p{N} .@_-]+$/u, "Usa solo letras, números, espacios y . @ _ -");
