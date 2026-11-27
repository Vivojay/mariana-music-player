package org.marianaplayer.wear;

import android.app.Activity;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.view.View;
import android.widget.*;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.Collections;
import org.json.*;

final class WatchThemes {
    static void install(Activity app, LinearLayout ui, TextView status) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(app.getAssets().open("theme_presets.json"),"UTF-8"))) {
            StringBuilder json = new StringBuilder();
            for (String line; (line = reader.readLine()) != null;) json.append(line);
            JSONObject themes = new JSONObject(json.toString());
            ArrayList<String> keys = new ArrayList<>();
            themes.keys().forEachRemaining(keys::add);
            Collections.sort(keys);
            if (keys.isEmpty()) return;
            SharedPreferences prefs = app.getPreferences(Activity.MODE_PRIVATE);
            TextView label = new TextView(app); label.setText("Theme"); ui.addView(label);
            Spinner picker = new Spinner(app);
            ArrayList<String> names = new ArrayList<>();
            for (String key : keys) names.add(themes.getJSONObject(key).getString("name"));
            ArrayAdapter<String> choices = new ArrayAdapter<>(app,android.R.layout.simple_spinner_dropdown_item,names);
            picker.setContentDescription("Theme"); picker.setAdapter(choices); ui.addView(picker);
            EditText accent = new EditText(app); accent.setSingleLine(true); accent.setHint("Accent #RRGGBB");
            accent.setText(prefs.getString("accent","")); ui.addView(accent);
            Button apply = new Button(app); apply.setText("Apply accent"); ui.addView(apply);
            Runnable repaint = () -> {
                int index = picker.getSelectedItemPosition();
                if (index < 0 || index >= keys.size()) return;
                String key = keys.get(index);
                JSONObject chrome = themes.optJSONObject(key).optJSONObject("chrome");
                String override = prefs.getString("accent","");
                int color = Color.parseColor(override.matches("#[0-9a-fA-F]{6}") ? override : chrome.optString("accent").substring(0,7));
                int text = Color.parseColor(chrome.optString("text").substring(0,7));
                int bg = Color.parseColor(chrome.optString("background").substring(0,7));
                ui.setBackgroundColor(bg);
                for (int i=0; i<ui.getChildCount(); i++) {
                    View child=ui.getChildAt(i);
                    if (child instanceof Button) {
                        ((Button)child).setTextColor(bg); child.setBackgroundTintList(ColorStateList.valueOf(color));
                    } else if (child instanceof TextView) ((TextView)child).setTextColor(text);
                }
                prefs.edit().putString("theme",key).apply();
            };
            picker.setSelection(Math.max(0,keys.indexOf(prefs.getString("theme","aurora"))));
            picker.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
                public void onItemSelected(AdapterView<?> parent, View view, int pos, long id) { repaint.run(); }
                public void onNothingSelected(AdapterView<?> parent) {}
            });
            apply.setOnClickListener(v -> {
                String value = accent.getText().toString().trim();
                if (!value.isEmpty() && !value.matches("#[0-9a-fA-F]{6}")) { status.setText("Use #RRGGBB or clear the field."); return; }
                prefs.edit().putString("accent",value).apply(); repaint.run();
            });
            repaint.run();
        } catch (IOException | JSONException e) { status.setText("Theme file unavailable"); }
    }
}
