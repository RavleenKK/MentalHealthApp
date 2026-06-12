import 'package:flutter/material.dart';

class TextPage extends StatefulWidget {
  const TextPage({super.key});

  @override
  State<TextPage> createState() => _TextPageState();
}

class _TextPageState extends State<TextPage>
    with SingleTickerProviderStateMixin {
  final TextEditingController _controller = TextEditingController();
  String _saved = '';
  late final AnimationController _animCtrl;

  @override
  void initState() {
    super.initState();
    _animCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 450),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    _animCtrl.dispose();
    super.dispose();
  }

  void _save() {
    setState(() {
      _saved = _controller.text.trim();
    });
    _animCtrl.forward(from: 0);
    FocusScope.of(context).unfocus();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      // transparent / elevated AppBar for modern feel
      appBar: AppBar(
        title: const Text('Write — Text Entry'),
        centerTitle: true,
        elevation: 0,
        backgroundColor: Colors.transparent,
        foregroundColor: theme.colorScheme.primary,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 16),
          child: Column(
            children: [
              // Card-like input area
              Container(
                decoration: BoxDecoration(
                  color: theme.colorScheme.surface,
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.05),
                      blurRadius: 18,
                      offset: const Offset(0, 8),
                    ),
                  ],
                ),
                padding: const EdgeInsets.all(14),
                child: Column(
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.edit_note, size: 18),
                        const SizedBox(width: 8),
                        Text(
                          'New text entry',
                          style: theme.textTheme.titleMedium,
                        ),
                        const Spacer(),
                        // small hint chip
                        Chip(
                          label: const Text('Private'),
                          backgroundColor: theme.colorScheme.primary
                              .withOpacity(0.1),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    // rounded TextField
                    TextField(
                      controller: _controller,
                      minLines: 4,
                      maxLines: 8,
                      decoration: InputDecoration(
                        hintText: 'Share what\'s on your mind...',
                        filled: true,
                        fillColor: theme.colorScheme.background,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide.none,
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 14,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        // clear button
                        TextButton.icon(
                          onPressed: () {
                            _controller.clear();
                          },
                          icon: const Icon(Icons.clear),
                          label: const Text('Clear'),
                        ),
                        const Spacer(),
                        ElevatedButton.icon(
                          onPressed: _save,
                          icon: const Icon(Icons.save),
                          label: const Text('Save'),
                          style: ElevatedButton.styleFrom(
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 18),

              // Display area for saved text with subtle animation
              SizeTransition(
                sizeFactor: CurvedAnimation(
                  parent: _animCtrl,
                  curve: Curves.easeOut,
                ),
                axisAlignment: -1,
                child: _saved.isEmpty
                    ? const SizedBox.shrink()
                    : Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: theme.colorScheme.secondary.withOpacity(0.06),
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: theme.dividerColor),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const Icon(Icons.note, size: 18),
                                const SizedBox(width: 8),
                                Text(
                                  'Saved entry',
                                  style: theme.textTheme.titleMedium,
                                ),
                                const Spacer(),
                                Text(
                                  _formattedNow(),
                                  style: theme.textTheme.bodySmall,
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            Text(
                              _saved,
                              style: const TextStyle(fontSize: 16, height: 1.4),
                            ),
                          ],
                        ),
                      ),
              ),
              const Spacer(),
              // subtle footer credit / image usage note (optional)
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: const [
                  Text(
                    'Tip: Keep entries short and honest.',
                    style: TextStyle(color: Colors.black54),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _formattedNow() {
    final now = DateTime.now();
    return '${now.year}-${_two(now.month)}-${_two(now.day)} ${_two(now.hour)}:${_two(now.minute)}';
  }

  String _two(int n) => n.toString().padLeft(2, '0');
}
