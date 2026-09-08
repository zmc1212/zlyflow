import { useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { getDirectorOperation } from "./director-api"
import { directorOperationStorageKey } from "./director-operation-controller"

/** Restores a persisted operation without creating or retrying it on navigation. */
export function useDirectorOperation(projectId: string) {
  const operationStorageKey = directorOperationStorageKey(projectId)
  const [activeOperationId, setActiveOperationId] = useState<string | null>(() => (
    typeof window === "undefined" ? null : window.localStorage.getItem(operationStorageKey)
  ))
  const handledOperationIdsRef = useRef(new Set<string>())
  const operationToastKeysRef = useRef(new Map<string, string>())
  const operationQuery = useQuery({
    queryKey: ["director-operation", activeOperationId],
    queryFn: () => getDirectorOperation(activeOperationId as string),
    enabled: Boolean(activeOperationId),
    refetchInterval: activeOperationId ? 1200 : false,
    retry: false,
  })
  return { operationStorageKey, activeOperationId, setActiveOperationId, handledOperationIdsRef, operationToastKeysRef, operationQuery }
}
