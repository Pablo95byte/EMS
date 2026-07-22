package com.pablo.rpecalculator

/**
 * Tabella RPE (Reactive Training Systems / Mike Tuchscherer), la stessa usata da
 * rpecalculator.com: per ogni coppia (RPE, ripetizioni) indica la percentuale
 * dell'1RM stimato che quel set rappresenta.
 */
object RpeChart {

    val rpeValues: List<Double> = listOf(10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0)
    val repsRange: IntRange = 1..12

    // Righe indicizzate per RPE, colonne per ripetizioni (1..12), valori in % dell'1RM.
    private val table: Map<Double, DoubleArray> = mapOf(
        10.0 to doubleArrayOf(100.0, 95.5, 92.2, 89.2, 86.3, 83.7, 81.1, 78.6, 76.2, 73.9, 70.7, 68.0),
        9.5 to doubleArrayOf(97.8, 93.9, 90.7, 87.8, 85.0, 82.4, 79.9, 77.4, 75.1, 72.3, 69.4, 66.7),
        9.0 to doubleArrayOf(95.5, 92.2, 89.2, 86.3, 83.7, 81.1, 78.6, 76.2, 73.9, 70.7, 68.0, 65.3),
        8.5 to doubleArrayOf(93.9, 90.7, 87.8, 85.0, 82.4, 79.9, 77.4, 75.1, 72.3, 69.4, 66.7, 64.0),
        8.0 to doubleArrayOf(92.2, 89.2, 86.3, 83.7, 81.1, 78.6, 76.2, 73.9, 70.7, 68.0, 65.3, 62.6),
        7.5 to doubleArrayOf(90.7, 87.8, 85.0, 82.4, 79.9, 77.4, 75.1, 72.3, 69.4, 66.7, 64.0, 61.3),
        7.0 to doubleArrayOf(89.2, 86.3, 83.7, 81.1, 78.6, 76.2, 73.9, 70.7, 68.0, 65.3, 62.6, 59.9),
        6.5 to doubleArrayOf(87.8, 85.0, 82.4, 79.9, 77.4, 75.1, 72.3, 69.4, 66.7, 64.0, 61.3, 58.6),
        6.0 to doubleArrayOf(86.3, 83.7, 81.1, 78.6, 76.2, 73.9, 70.7, 68.0, 65.3, 62.6, 59.9, 57.4),
    )

    /**
     * Percentuale dell'1RM per il set dato, o null se fuori tabella.
     */
    fun percentOf1Rm(rpe: Double, reps: Int): Double? {
        if (reps !in repsRange) return null
        return table[rpe]?.get(reps - 1)
    }
}
