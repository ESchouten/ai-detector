<script lang="ts">
	import { buttonVariants } from '$lib/components/ui/button';
	import * as AlertDialog from '$lib/components/ui/alert-dialog';
	// The last row of an editor: removes what is being edited, after asking.
	let {
		trigger,
		title,
		description,
		keep,
		confirm,
		disabled,
		onconfirm
	}: {
		trigger: string;
		title: string;
		description: string;
		keep: string;
		confirm: string;
		disabled: boolean;
		onconfirm: () => void;
	} = $props();
	let open = $state(false);
</script>

<div class="border-t pt-5">
	<AlertDialog.Root bind:open>
		<AlertDialog.Trigger
			type="button"
			class={buttonVariants({ variant: 'ghost', size: 'sm' }) +
				' -ml-2.5 text-danger-foreground hover:text-danger-foreground'}
			{disabled}>{trigger}</AlertDialog.Trigger
		>
		<AlertDialog.Content>
			<AlertDialog.Header>
				<AlertDialog.Title>{title}</AlertDialog.Title>
				<AlertDialog.Description>{description}</AlertDialog.Description>
			</AlertDialog.Header>
			<AlertDialog.Footer>
				<AlertDialog.Cancel type="button">{keep}</AlertDialog.Cancel>
				<AlertDialog.Action
					type="button"
					class={buttonVariants({ variant: 'destructive' })}
					onclick={() => {
						open = false;
						onconfirm();
					}}>{confirm}</AlertDialog.Action
				>
			</AlertDialog.Footer>
		</AlertDialog.Content>
	</AlertDialog.Root>
</div>
