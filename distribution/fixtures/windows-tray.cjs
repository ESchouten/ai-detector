process.stdout.write('open\nunknown\nquit\n');
process.stdin.resume();
process.stdin.on('end', () => process.exit(0));
