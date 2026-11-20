"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, CircleAlert, Clock, Info } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DECISION_LABELS, type Decision } from "@/lib/issues";

interface Props {
  status: "queued" | "applied" | "failed" | "superseded";
  decision: Decision;
  reviewer: string;
  error: string | null;
  nextHref: string | null;
}

// Fast at first (the worker applies a decision in about a second), then slower: while the
// worker propagates (normalize + consolidate, a few minutes on the full data) decisions wait.
const pollDelay = (n: number) => (n < 20 ? 1500 : 5000);
const SLOW_AFTER = 40; // ~2 min
const MAX_POLLS = 80; // ~5.5 min

/** State of the latest decision. While it waits for the worker, re-renders the page
 *  (router.refresh) until the worker applies it. */
export function DecisionStatus({ status, decision, reviewer, error, nextHref }: Props) {
  const router = useRouter();
  const [polls, setPolls] = useState(0);

  useEffect(() => {
    if (status !== "queued" || polls >= MAX_POLLS) return;
    const t = setTimeout(() => {
      router.refresh();
      setPolls((p) => p + 1);
    }, pollDelay(polls));
    return () => clearTimeout(t);
  }, [status, polls, router]);

  const next = nextHref && (
    <div className="mt-3">
      <Button asChild size="sm">
        <Link href={nextHref}>Siguiente caso</Link>
      </Button>
    </div>
  );

  if (status === "queued") {
    return (
      <Alert role="status">
        <Clock aria-hidden />
        <AlertTitle>En cola: {DECISION_LABELS[decision]}</AlertTitle>
        <AlertDescription>
          {polls < SLOW_AFTER
            ? "Esperando a que el worker la aplique…"
            : polls < MAX_POLLS
              ? "Sigue en cola: el worker puede estar recalculando la base (tarda unos minutos)."
              : "El worker no ha respondido. ¿Está corriendo `vehicle-scraper kb review worker`?"}
          {next}
        </AlertDescription>
      </Alert>
    );
  }
  if (status === "applied") {
    return (
      <Alert role="status">
        <CheckCircle2 aria-hidden />
        <AlertTitle>
          Aplicada: {DECISION_LABELS[decision]} por {reviewer}
        </AlertTitle>
        <AlertDescription>
          Los casos que dependían de este aparecen cuando el worker recalcula (normalize + consolidate).
          {next}
        </AlertDescription>
      </Alert>
    );
  }
  if (status === "failed") {
    return (
      <Alert variant="destructive" role="alert">
        <CircleAlert aria-hidden />
        <AlertTitle>No se aplicó</AlertTitle>
        <AlertDescription>{error ?? "Error desconocido."} Puedes enviar otra decisión.</AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert role="status">
      <Info aria-hidden />
      <AlertTitle>Ya estaba decidido</AlertTitle>
      <AlertDescription>
        {error ?? "Otra persona o un CSV decidió este caso antes."}
        {next}
      </AlertDescription>
    </Alert>
  );
}
