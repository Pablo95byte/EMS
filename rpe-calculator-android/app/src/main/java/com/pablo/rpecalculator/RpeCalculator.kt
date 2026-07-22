package com.pablo.rpecalculator

import kotlin.math.roundToInt

enum class WeightUnit(val label: String, val defaultIncrement: Double) {
    KG("kg", 2.5),
    LB("lb", 5.0),
}

object RpeCalculator {

    /**
     * 1RM stimato a partire da un set eseguito: peso, ripetizioni e RPE percepito.
     */
    fun estimateOneRepMax(weight: Double, reps: Int, rpe: Double): Double? {
        if (weight <= 0.0) return null
        val pct = RpeChart.percentOf1Rm(rpe, reps) ?: return null
        return weight / pct * 100.0
    }

    /**
     * Peso da caricare per ottenere il target di ripetizioni al RPE voluto,
     * dato l'1RM stimato. Non arrotondato.
     */
    fun targetWeight(oneRepMax: Double, targetReps: Int, targetRpe: Double): Double? {
        if (oneRepMax <= 0.0) return null
        val pct = RpeChart.percentOf1Rm(targetRpe, targetReps) ?: return null
        return oneRepMax * pct / 100.0
    }

    /**
     * Arrotonda al multiplo di [increment] più vicino (es. 2.5 kg o 5 lb),
     * il minimo caricabile su un bilanciere.
     */
    fun roundToIncrement(weight: Double, increment: Double): Double {
        if (increment <= 0.0) return weight
        return (weight / increment).roundToInt() * increment
    }
}
