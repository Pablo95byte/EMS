package com.pablo.rpecalculator

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.pablo.rpecalculator.ui.theme.RpeCalculatorTheme
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            RpeCalculatorTheme {
                RpeCalculatorApp()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RpeCalculatorApp() {
    var unit by rememberSaveable { mutableStateOf(WeightUnit.KG) }

    // Set eseguito
    var weightText by rememberSaveable { mutableStateOf("") }
    var doneReps by rememberSaveable { mutableStateOf(5) }
    var doneRpe by rememberSaveable { mutableStateOf(8.0) }

    // Set target
    var targetReps by rememberSaveable { mutableStateOf(5) }
    var targetRpe by rememberSaveable { mutableStateOf(8.0) }

    val weight = weightText.replace(',', '.').toDoubleOrNull()
    val oneRepMax = weight?.let { RpeCalculator.estimateOneRepMax(it, doneReps, doneRpe) }
    val targetRaw = oneRepMax?.let { RpeCalculator.targetWeight(it, targetReps, targetRpe) }
    val targetRounded = targetRaw?.let { RpeCalculator.roundToIncrement(it, unit.defaultIncrement) }

    Scaffold(
        topBar = { CenterAlignedTopAppBar(title = { Text("RPE Calculator") }) },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            UnitSelector(unit = unit, onUnitChange = { unit = it })

            Card {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("Set eseguito", style = MaterialTheme.typography.titleMedium)
                    OutlinedTextField(
                        value = weightText,
                        onValueChange = { weightText = it },
                        label = { Text("Peso sollevato (${unit.label})") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        NumberDropdown(
                            label = "Ripetizioni",
                            options = RpeChart.repsRange.toList(),
                            selected = doneReps,
                            format = { it.toString() },
                            onSelected = { doneReps = it },
                            modifier = Modifier.weight(1f),
                        )
                        NumberDropdown(
                            label = "RPE",
                            options = RpeChart.rpeValues.sorted(),
                            selected = doneRpe,
                            format = { formatRpe(it) },
                            onSelected = { doneRpe = it },
                            modifier = Modifier.weight(1f),
                        )
                    }
                    if (oneRepMax != null) {
                        HorizontalDivider()
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("1RM stimato:", style = MaterialTheme.typography.bodyLarge)
                            Spacer(Modifier.width(8.dp))
                            Text(
                                "${formatWeight(oneRepMax)} ${unit.label}",
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }
            }

            Card {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("Set target", style = MaterialTheme.typography.titleMedium)
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        NumberDropdown(
                            label = "Ripetizioni",
                            options = RpeChart.repsRange.toList(),
                            selected = targetReps,
                            format = { it.toString() },
                            onSelected = { targetReps = it },
                            modifier = Modifier.weight(1f),
                        )
                        NumberDropdown(
                            label = "RPE",
                            options = RpeChart.rpeValues.sorted(),
                            selected = targetRpe,
                            format = { formatRpe(it) },
                            onSelected = { targetRpe = it },
                            modifier = Modifier.weight(1f),
                        )
                    }
                    HorizontalDivider()
                    if (targetRounded != null && targetRaw != null) {
                        Column {
                            Text(
                                "${formatWeight(targetRounded)} ${unit.label}",
                                style = MaterialTheme.typography.displaySmall,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.primary,
                            )
                            Text(
                                "esatto: ${formatWeight(targetRaw)} ${unit.label} — " +
                                    "arrotondato a ${formatWeight(unit.defaultIncrement)} ${unit.label}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    } else {
                        Text(
                            "Inserisci il set eseguito per calcolare il peso target.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            if (oneRepMax != null) {
                Card(colors = CardDefaults.cardColors()) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(
                            "Pesi a RPE ${formatRpe(targetRpe)} per ripetizioni",
                            style = MaterialTheme.typography.titleMedium,
                        )
                        Row(modifier = Modifier.horizontalScroll(rememberScrollState())) {
                            RpeChart.repsRange.forEach { reps ->
                                val w = RpeCalculator.targetWeight(oneRepMax, reps, targetRpe)
                                    ?.let { RpeCalculator.roundToIncrement(it, unit.defaultIncrement) }
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    modifier = Modifier.width(64.dp),
                                ) {
                                    Text(
                                        "$reps",
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    Spacer(Modifier.height(4.dp))
                                    Text(
                                        w?.let { formatWeight(it) } ?: "—",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun UnitSelector(unit: WeightUnit, onUnitChange: (WeightUnit) -> Unit) {
    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
        WeightUnit.entries.forEachIndexed { index, u ->
            SegmentedButton(
                selected = unit == u,
                onClick = { onUnitChange(u) },
                shape = SegmentedButtonDefaults.itemShape(index = index, count = WeightUnit.entries.size),
            ) {
                Text(u.label)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun <T> NumberDropdown(
    label: String,
    options: List<T>,
    selected: T,
    format: (T) -> String,
    onSelected: (T) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = it },
        modifier = modifier,
    ) {
        OutlinedTextField(
            value = format(selected),
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier
                .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                .fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { option ->
                DropdownMenuItem(
                    text = { Text(format(option)) },
                    onClick = {
                        onSelected(option)
                        expanded = false
                    },
                )
            }
        }
    }
}

private fun formatRpe(rpe: Double): String =
    if (rpe % 1.0 == 0.0) rpe.toInt().toString() else String.format(Locale.US, "%.1f", rpe)

private fun formatWeight(weight: Double): String =
    if (weight % 1.0 == 0.0) weight.toInt().toString() else String.format(Locale.US, "%.1f", weight)
