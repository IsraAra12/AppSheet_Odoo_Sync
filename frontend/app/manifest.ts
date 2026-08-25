import type { MetadataRoute } from "next";

export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "RapyVet Pedidos",
    short_name: "RapyVet",
    description: "Captura pedidos de venta y envíalos a Odoo.",
    start_url: "/",
    display: "standalone",
    background_color: "#1a0b25",
    theme_color: "#8b458b",
    orientation: "portrait-primary",
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "maskable",
      },
    ],
  };
}
