package com.pablo.rpecalculator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RpeCalculatorTest {

    @Test
    fun `singola a RPE 10 e proprio l 1RM`() {
        val e1rm = RpeCalculator.estimateOneRepMax(100.0, 1, 10.0)
        assertEquals(100.0, e1rm!!, 0.001)
    }

    @Test
    fun `5 reps a RPE 8 corrisponde all 81 1 percento`() {
        // 81.1% dell'1RM -> con 100 kg sollevati l'1RM stimato è 123.3 kg
        val e1rm = RpeCalculator.estimateOneRepMax(100.0, 5, 8.0)
        assertEquals(100.0 / 81.1 * 100.0, e1rm!!, 0.001)
    }

    @Test
    fun `andata e ritorno sulla stessa cella restituisce il peso di partenza`() {
        val e1rm = RpeCalculator.estimateOneRepMax(140.0, 3, 9.0)!!
        val back = RpeCalculator.targetWeight(e1rm, 3, 9.0)!!
        assertEquals(140.0, back, 0.001)
    }

    @Test
    fun `peso target scende se il target RPE scende`() {
        val e1rm = 200.0
        val at9 = RpeCalculator.targetWeight(e1rm, 5, 9.0)!!
        val at7 = RpeCalculator.targetWeight(e1rm, 5, 7.0)!!
        assertEquals(true, at7 < at9)
    }

    @Test
    fun `reps fuori tabella restituisce null`() {
        assertNull(RpeCalculator.estimateOneRepMax(100.0, 13, 8.0))
        assertNull(RpeCalculator.estimateOneRepMax(100.0, 0, 8.0))
    }

    @Test
    fun `rpe fuori tabella restituisce null`() {
        assertNull(RpeCalculator.estimateOneRepMax(100.0, 5, 5.5))
        assertNull(RpeCalculator.estimateOneRepMax(100.0, 5, 10.5))
    }

    @Test
    fun `peso non positivo restituisce null`() {
        assertNull(RpeCalculator.estimateOneRepMax(0.0, 5, 8.0))
        assertNull(RpeCalculator.estimateOneRepMax(-50.0, 5, 8.0))
    }

    @Test
    fun `arrotondamento a 2 punto 5 kg`() {
        assertEquals(122.5, RpeCalculator.roundToIncrement(123.3, 2.5), 0.001)
        assertEquals(125.0, RpeCalculator.roundToIncrement(123.8, 2.5), 0.001)
        assertEquals(120.0, RpeCalculator.roundToIncrement(120.0, 2.5), 0.001)
    }

    @Test
    fun `arrotondamento a 5 lb`() {
        assertEquals(270.0, RpeCalculator.roundToIncrement(271.9, 5.0), 0.001)
        assertEquals(275.0, RpeCalculator.roundToIncrement(272.5, 5.0), 0.001)
    }

    @Test
    fun `la tabella e monotona su reps e rpe`() {
        for (rpe in RpeChart.rpeValues) {
            for (reps in 1 until 12) {
                val cur = RpeChart.percentOf1Rm(rpe, reps)!!
                val next = RpeChart.percentOf1Rm(rpe, reps + 1)!!
                assertEquals(true, next < cur)
            }
        }
        val sorted = RpeChart.rpeValues.sorted()
        for (reps in RpeChart.repsRange) {
            for (i in 0 until sorted.size - 1) {
                val lower = RpeChart.percentOf1Rm(sorted[i], reps)!!
                val higher = RpeChart.percentOf1Rm(sorted[i + 1], reps)!!
                assertEquals(true, lower < higher)
            }
        }
    }
}
