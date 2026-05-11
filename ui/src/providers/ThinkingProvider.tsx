"use client";

import React, { createContext, useContext, useState, useCallback } from "react";

interface ThinkingContextType {
  thinkingText: string;
  setThinkingText: (text: string) => void;
  appendThinkingText: (delta: string) => void;
  clearThinkingText: () => void;
  isThinking: boolean;
  setIsThinking: (isThinking: boolean) => void;
}

const ThinkingContext = createContext<ThinkingContextType | undefined>(
  undefined,
);

export function ThinkingProvider({ children }: { children: React.ReactNode }) {
  const [thinkingText, setThinkingText] = useState("");
  const [isThinking, setIsThinking] = useState(false); // [新增] 默认为 false

  const appendThinkingText = useCallback((delta: string) => {
    setThinkingText((prev) => prev + delta);
  }, []);

  const clearThinkingText = useCallback(() => {
    setThinkingText("");
  }, []);

  return (
    <ThinkingContext.Provider
      value={{
        thinkingText,
        setThinkingText,
        appendThinkingText,
        clearThinkingText,
        isThinking, // [新增]
        setIsThinking, // [新增]
      }}
    >
      {children}
    </ThinkingContext.Provider>
  );
}

export const useThinking = () => {
  const context = useContext(ThinkingContext);
  if (!context)
    throw new Error("useThinking must be used within a ThinkingProvider");
  return context;
};
