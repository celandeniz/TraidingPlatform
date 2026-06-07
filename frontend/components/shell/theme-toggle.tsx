"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const isLight = mounted && resolvedTheme === "light";
  return (
    <Button
      aria-label="Toggle light and dark theme"
      variant="outline"
      size="icon"
      onClick={() => setTheme(isLight ? "dark" : "light")}
      title="Toggle theme"
    >
      {isLight ? <Moon /> : <Sun />}
    </Button>
  );
}
