import type {PlaygroundStateData} from "@/oss/components/NewPlayground/hooks/usePlayground/types"

import {extractInputKeysFromSchema} from "../../../hooks/usePlayground/assets/generationHelpers"
import {isObjectMetadata} from "../genericTransformer/helpers/metadata"
import type {ConfigMetadata, EnhancedObjectConfig, OpenAPISpec} from "../genericTransformer/types"
import {toSnakeCase} from "../genericTransformer/utilities/string"

import type {EnhancedVariant, Message} from "./types"

function shouldIncludeValue(value: unknown): boolean {
    if (!value) return false
    if (Array.isArray(value) && value.length === 0) return false
    return true
}

export const checkValidity = (obj: Record<string, any>, metadata: ConfigMetadata) => {
    if (!isObjectMetadata(metadata)) return true

    for (const [propName, propMetadata] of Object.entries(metadata.properties)) {
        const snakeCasePropName = toSnakeCase(propName)
        // If property is required (not nullable) and value is missing or undefined
        if (
            propMetadata.nullable === false &&
            (!(snakeCasePropName in obj) || !obj[snakeCasePropName])
        ) {
            return false
        }
    }

    // TODO: REMOVE THIS EDGE CASE and COME UP WITH A CORRECTED GENERIC
    // SUBSTITUTION FOR THIS CHECK
    if (metadata.type === "object" && metadata.title === "Message") {
        const nullableKeys = Object.keys(metadata.properties)
            .map((key) => {
                const snaked = toSnakeCase(key)
                if (metadata.properties[key].nullable) {
                    return snaked
                } else {
                    return undefined
                }
            })
            .filter(Boolean) as string[]

        const allEmpty = nullableKeys.every((key) => {
            return !obj[key]
        })

        if (allEmpty) return false
    }
    return true
}
/**
 * Extract raw value based on metadata type
 */
export function extractValueByMetadata(
    _enhanced: Record<string, any> | null | undefined,
    allMetadata: Record<string, ConfigMetadata>,
): unknown {
    const enhanced = structuredClone(_enhanced)
    // Handle null/undefined
    if (!enhanced) return null

    // Handle primitive values
    if (typeof enhanced !== "object" || enhanced === null) {
        return enhanced
    }

    const metadata = allMetadata ? allMetadata[enhanced.__metadata] : null

    // Handle primitive enhanced values
    if (
        "value" in enhanced &&
        (!metadata ||
            metadata.type === "string" ||
            metadata.type === "number" ||
            metadata.type === "boolean")
    ) {
        return shouldIncludeValue(enhanced.value) ? enhanced.value : undefined
    }

    if (!metadata) {
        // If no metadata, return object without __ properties and null values
        const obj = Object.entries(enhanced)
            .filter(([key]) => !key.startsWith("__"))
            .reduce(
                (acc, [key, val]) => {
                    const extracted = extractValueByMetadata(val, allMetadata)
                    if (shouldIncludeValue(extracted)) {
                        acc[toSnakeCase(key)] = extracted
                    }
                    return acc
                },
                {} as Record<string, unknown>,
            )

        return Object.keys(obj).length > 0 ? obj : undefined
    }

    switch (metadata.type) {
        case "array": {
            if (!Array.isArray(enhanced.value)) return undefined
            const arr = enhanced.value
                .map((item: Record<string, any>) => {
                    return extractValueByMetadata(item, allMetadata)
                })
                .filter(shouldIncludeValue)
                .filter(Boolean)
            return arr.length > 0 ? arr : undefined
        }
        case "object": {
            const obj = Object.entries(enhanced)
                .filter(([key]) => !key.startsWith("__"))
                .reduce(
                    (acc, [key, val]) => {
                        const extracted = extractValueByMetadata(val, allMetadata)
                        if (shouldIncludeValue(extracted)) {
                            acc[toSnakeCase(key)] = extracted
                        }
                        return acc
                    },
                    {} as Record<string, unknown>,
                )

            return Object.keys(obj).length > 0 &&
                checkValidity(obj, allMetadata[enhanced.__metadata])
                ? obj
                : undefined
        }
        default:
            return shouldIncludeValue(enhanced.value) ? enhanced.value : undefined
    }
}

/**
 * Extract input values from an enhanced input row
 */
function extractInputValues(
    variant: EnhancedVariant,
    inputRow: Record<string, any>,
): Record<string, string> {
    const variantInputs = variant.prompts.flatMap((prompt) => {
        return (prompt.inputKeys?.value || []).map((keyValue) => keyValue.value)
    })
    return Object.entries(inputRow).reduce(
        (acc, [key, value]) => {
            // Skip metadata, id, and result fields
            if (
                key !== "__id" &&
                key !== "__metadata" &&
                key !== "__result" &&
                variantInputs.includes(key)
            ) {
                acc[key] = value.value
            }
            return acc
        },
        {} as Record<string, string>,
    )
}

/**
 * Transform EnhancedVariant back to API request shape
 */
export function transformToRequestBody({
    variant,
    inputRow,
    messageRow,
    allMetadata = {},
    chatHistory,
    spec,
}: {
    variant: EnhancedVariant
    inputRow?: PlaygroundStateData["generationData"]["inputs"]["value"][number]
    messageRow?: PlaygroundStateData["generationData"]["messages"]["value"][number]
    allMetadata: Record<string, ConfigMetadata>
    chatHistory?: Message[]
    spec: OpenAPISpec
}): Record<string, any> {
    const data = {} as Record<string, any>

    const promptConfigs = variant.prompts.reduce(
        (acc, prompt) => {
            const extracted = extractValueByMetadata(prompt, allMetadata)
            const name = prompt.__name
            if (!name) return acc

            acc[name] = extracted
            return acc
        },
        {} as Record<string, any>,
    )

    const customConfigs =
        (extractValueByMetadata(variant.customProperties, allMetadata) as Record<string, any>) || {}

    data.ag_config = {
        ...promptConfigs,
        ...customConfigs,
    }

    if (inputRow) {
        if (!variant.isCustom) {
            data.inputs = extractInputValues(variant, inputRow)
        } else if (spec) {
            const inputKeys = extractInputKeysFromSchema(spec)
            for (const key of inputKeys) {
                const value = (
                    inputRow?.[key as keyof typeof inputRow] as EnhancedObjectConfig<any>
                ).value

                if (value) {
                    data[key] = value
                }
            }
        }
    }

    if (variant.isChat) {
        data.messages = []
        if (chatHistory) {
            data.messages.push(...chatHistory)
        } else {
            const messageHistory = messageRow?.history.value || []

            data.messages.push(
                ...messageHistory
                    .flatMap((historyMessage) => {
                        const messages = [extractValueByMetadata(historyMessage, allMetadata)]

                        if (historyMessage.__runs && historyMessage.__runs[variant.id]?.message) {
                            messages.push(
                                extractValueByMetadata(
                                    historyMessage.__runs[variant.id]?.message,
                                    allMetadata,
                                ),
                            )
                        }

                        return messages
                    })
                    .filter(Boolean),
            )
        }
    }

    return data
}
