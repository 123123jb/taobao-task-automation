package io.github.taobaotasks.assistant;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** One short-lived view of the foreground window. Never persisted. */
final class Frame {
    final String pkg;
    final int width, height;
    final boolean visual;
    final List<Node> nodes = new ArrayList<>();

    Frame(String pkg, int width, int height, boolean visual) {
        this.pkg = pkg; this.width = width; this.height = height; this.visual = visual;
    }

    static final class Node {
        final String text, description, id, type;
        final int parent, left, top, right, bottom;
        final boolean clickable, editable;
        Node(String text, String description, String id, String type, int parent,
             int left, int top, int right, int bottom, boolean clickable, boolean editable) {
            this.text = text; this.description = description; this.id = id; this.type = type;
            this.parent = parent; this.left = left; this.top = top; this.right = right;
            this.bottom = bottom; this.clickable = clickable; this.editable = editable;
        }
        String label() { return text.isEmpty() ? description : text; }
        int x() { return (left + right) / 2; }
        int y() { return (top + bottom) / 2; }
    }

    static final class Task {
        final String key, title;
        final int current, total;
        final Node button;
        Task(String title, Node button) {
            this.title = title; this.key = TaskRules.key(title); this.button = button;
            int[] p = TaskRules.progress(title); current = p[0]; total = p[1];
        }
        boolean available() { return button.label().contains("去完成") && current < total; }
    }

    String text() {
        StringBuilder result = new StringBuilder();
        for (Node node : nodes) if (!node.label().isEmpty()) result.append(node.label()).append('\n');
        return result.toString();
    }
    Node exact(String label) {
        for (Node node : nodes) if (node.label().trim().equals(label)) return node;
        return null;
    }
    Node contains(String label) {
        for (Node node : nodes) if (node.label().contains(label)) return node;
        return null;
    }
    boolean panel() { return exact("做任务赚能量") != null && contains("累计任务奖励") != null; }

    private boolean under(int index, int ancestor) {
        for (int count = 0; index >= 0 && index < nodes.size() && count < 80; count++) {
            if (index == ancestor) return true;
            index = nodes.get(index).parent;
        }
        return false;
    }
    private int panelRoot() {
        Node title = exact("做任务赚能量"), reward = contains("累计任务奖励");
        if (title == null || reward == null || visual) return -1;
        int rewardIndex = nodes.indexOf(reward), at = nodes.indexOf(title);
        for (int count = 0; at >= 0 && count < 80; count++) {
            if (nodes.get(at).type.endsWith("WebView")) return -1;
            if (under(rewardIndex, at)) return at;
            at = nodes.get(at).parent;
        }
        return -1;
    }
    boolean inPanel(Node node) {
        Node title = exact("做任务赚能量");
        if (!panel() || title == null || node.top < title.top) return false;
        int root = panelRoot();
        return visual || (root >= 0 && under(nodes.indexOf(node), root));
    }
    int cumulative() {
        if (!panel()) return -1;
        Pattern pattern = Pattern.compile("\\s*(\\d+)\\s*/\\s*50\\s*");
        for (Node node : nodes) if (inPanel(node)) {
            Matcher m = pattern.matcher(node.label());
            if (m.matches()) {
                try { return Integer.parseInt(m.group(1)); }
                catch (NumberFormatException ignored) { return -1; }
            }
        }
        return -1;
    }
    List<Task> tasks() {
        List<Task> result = new ArrayList<>();
        if (!panel()) return result;
        for (Node button : nodes) {
            if (!inPanel(button) || !(button.label().equals("去完成") || button.label().equals("已完成"))) continue;
            Node nearest = null;
            int distance = Integer.MAX_VALUE;
            for (Node title : nodes) {
                if (!inPanel(title) || !TaskRules.PROGRESS.matcher(title.label()).find()) continue;
                int dy = Math.abs(title.y() - button.y());
                if (dy <= height * .055 && dy < distance) { nearest = title; distance = dy; }
            }
            if (nearest != null) {
                String title = nearest.label();
                // Timings are often rendered on a separate line underneath the task name.
                for (Node detail : nodes) if (inPanel(detail) && detail != nearest
                        && detail.top >= nearest.top && detail.top - nearest.bottom < height * .035
                        && detail.left < button.left && detail.label().matches(".*\\d+\\s*(秒|s).*")) {
                    title += " " + detail.label();
                }
                result.add(new Task(title, button));
            }
        }
        return result;
    }
}
