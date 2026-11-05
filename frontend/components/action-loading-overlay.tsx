"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { subscribePendingRequests } from "@/lib/api";

/** Tiempo que la pantalla de carga bloquea la app después de cada acción. */
const ACTION_LOADING_MS = 30_000;
/** Tope de seguridad: si una solicitud a Odoo no termina, el bloqueo se quita de todos modos. */
const MAX_ACTION_LOADING_MS = 75_000;
const TICK_MS = 250;

// Cuenta como "acción" tocar un botón, enlace, pestaña o casilla, enviar un formulario
// o cambiar una lista desplegable. Escribir en un campo o desplazarse no cuenta.
// Para que un control no active la pantalla de carga, ponle el atributo data-no-action-loading.
const ACTION_SELECTOR = [
  "button",
  "a[href]",
  '[role="button"]',
  '[role="tab"]',
  '[role="menuitem"]',
  '[role="switch"]',
  '[role="checkbox"]',
  'input[type="checkbox"]',
  'input[type="radio"]',
  'input[type="submit"]',
  'input[type="button"]',
  "summary",
].join(",");

const EXCLUDED_SELECTOR = "[data-no-action-loading]";

function isDisabled(element: Element) {
  return (element as HTMLButtonElement).disabled === true || element.getAttribute("aria-disabled") === "true";
}

/**
 * Pantalla de carga invisible: después de cada acción, una capa transparente cubre la app
 * durante 30 segundos (o hasta que Odoo termine de responder) y no deja tocar nada ni usar
 * el teclado. No se ve nada en pantalla; solo los lectores de pantalla anuncian "Procesando".
 */
export function ActionLoadingOverlay({ children }: { children: ReactNode }) {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const activeRef = useRef(false);
  const pendingRef = useRef(0);

  useEffect(
    () =>
      subscribePendingRequests((count) => {
        pendingRef.current = count;
      }),
    [],
  );

  useEffect(() => {
    const start = () => {
      if (activeRef.current) return;
      activeRef.current = true;
      setStartedAt(Date.now());
    };
    // Se activa en la siguiente vuelta del navegador, cuando la acción ya se procesó,
    // para no interferir con el clic, el envío del formulario ni con abrir WhatsApp.
    const schedule = () => window.setTimeout(start, 0);

    const onClick = (event: MouseEvent) => {
      if (activeRef.current || !(event.target instanceof Element)) return;
      const control = event.target.closest(ACTION_SELECTOR);
      if (!control || isDisabled(control) || control.closest(EXCLUDED_SELECTOR)) return;
      schedule();
    };
    const onSubmit = (event: Event) => {
      if (activeRef.current || !(event.target instanceof Element) || event.target.closest(EXCLUDED_SELECTOR)) return;
      schedule();
    };
    const onChange = (event: Event) => {
      if (activeRef.current || !(event.target instanceof HTMLSelectElement) || event.target.closest(EXCLUDED_SELECTOR)) return;
      schedule();
    };

    document.addEventListener("click", onClick, true);
    document.addEventListener("submit", onSubmit, true);
    document.addEventListener("change", onChange, true);
    return () => {
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("submit", onSubmit, true);
      document.removeEventListener("change", onChange, true);
    };
  }, []);

  useEffect(() => {
    if (startedAt === null) return;
    // Mientras está activa, el teclado no llega a la app (por ejemplo, Escape o Enter).
    const blockKeys = (event: KeyboardEvent) => event.stopPropagation();
    window.addEventListener("keydown", blockKeys, true);
    const timer = window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const finished = elapsed >= ACTION_LOADING_MS && pendingRef.current === 0;
      if (finished || elapsed >= MAX_ACTION_LOADING_MS) {
        activeRef.current = false;
        setStartedAt(null);
      }
    }, TICK_MS);
    return () => {
      window.removeEventListener("keydown", blockKeys, true);
      window.clearInterval(timer);
    };
  }, [startedAt]);

  const active = startedAt !== null;

  return (
    <>
      <div className="action-loading-root" inert={active} aria-busy={active || undefined}>
        {children}
      </div>
      {active && (
        <div className="action-loading" role="status" aria-live="polite">
          <span className="action-loading-sr">Procesando…</span>
        </div>
      )}
    </>
  );
}
