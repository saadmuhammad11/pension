<?php
/**
 *
 * This file is part of HESK - PHP Help Desk Software.
 *
 * (c) Copyright Klemen Stirn. All rights reserved.
 * https://www.hesk.com
 *
 * For the full copyright and license agreement information visit
 * https://www.hesk.com/eula.php
 *
 */

/* Check if this is a valid include */
if (!defined('IN_SCRIPT')) {die('Invalid attempt');}

// Ticket priority
switch ($ticket['priority'])
{
	case 0:
		$ticket['priority']='<b>'.$hesklang['critical'].'</b>';
		break;
	case 1:
		$ticket['priority']='<b>'.$hesklang['high'].'</b>';
		break;
	case 2:
		$ticket['priority']=$hesklang['medium'];
		break;
	default:
		$ticket['priority']=$hesklang['low'];
}

// Set last replier name
if ($ticket['lastreplier'])
{
	if (empty($ticket['repliername']))
	{
		$ticket['repliername'] = $hesklang['staff'];
	}
}
else
{
	$ticket['repliername'] = $ticket['name'];
}

// Other variables that need processing
$ticket['dt'] = hesk_date($ticket['dt'], true);
$ticket['lastchange'] = hesk_date($ticket['lastchange'], true);
$random=mt_rand(10000,99999);

// Print ticket head
echo '
<table align=center border="1">
<tr>
   <center>
		<b>  ' . $ticket[''] . ' ONE WINDOW OPERATION CENTER 
		 <br>' . $ticket[''] . ' Accountant General Punjab, Lahore. 
		 <br>' . $ticket[''] . ' For Information & Enquiry 042-99210178 
	   <br>' . $ticket[''] . '-------------------------------------------------------------
    </b>
     <br>' . $hesklang['category'] . '***	  <b>  ' . $category['name'] . ' </b>  
     <br>' . $hesklang[''] . 'Ticket ID *** <b>  ' . $ticket['id']     . ' </b>
     <br>' . $ticket[''] . '-------------------------------------------------------------
     </center>
</tr>
';

// Custom fields
foreach ($hesk_settings['custom_fields'] as $k=>$v)
{
	if ( ($v['use'] == 1 || (! empty($_SESSION['id']) && $v['use'] == 2)) && hesk_is_custom_field_in_category($k, $ticket['category']) )
	{
  	switch ($v['type'])
		{
			case 'date':
				$ticket[$k] = hesk_custom_date_display_format($ticket[$k], $v['value']['date_format']);
				break;
		}
	?>
	<tr>
		<td> <?php echo $v['name:']; ?> </td>
		<td> <b><?php echo hesk_unhortenUrl($ticket[$k]); ?></b></td>
	</tr>
	<?php
	}
}


echo '

<tr>
	<td>' . $hesklang[''] . 'Ticket Entered By:</td>
	<td><b>' . $ticket['name'] . '</b> </td>
</tr>
<tr>
	<td>' . $hesklang['created_on'] . ':</td>
	<td><b>' . $ticket['dt'] . '</b></td>
</tr>

';

// Assigned to?
if ($ticket['owner'] && ! empty($_SESSION['id']) )
{
	$ticket['owner'] = hesk_getOwnerName($ticket['owner']);
	echo'
	<tr>
		<td>' . $hesklang['taso3'] . '</td>
		<td><b>' . $ticket['owner'] . '</b></td>
	</tr>
	';
}

// Continue with ticket head
echo '
<tr>
	<td>' . $hesklang['last_replier'] . ':</td>
	<td><b>' . $ticket['repliername'] . '</b></td>
</tr>

';

// Show IP and time worked to staff
if ( ! empty($_SESSION['id']) )
{
	echo '
	';
}

echo '
	  ';


// Close ticket head table
echo '</table>';



///////////////////////////////////////////////////////
// Print initial ticket message
if ($ticket['message'] != '')
{
   echo '<p align=center>' . hesk_unhortenUrl($ticket['message']) . '</p align=center>';
}

// Remove these lines to print messages from the staff till bottom or all code
// Print replies
while ($reply = hesk_dbFetchAssoc($res))
{
	$reply['dt'] = hesk_date($reply['dt'], true);

    echo '
    <hr />

	<table align=center border="0">
	<tr>
		<td>' . $hesklang['date'] . ':</td>
		<td>' . $reply['dt'] . '</td>
	</tr>
	<tr>
		<td>' . $hesklang['name'] . ':</td>
		<td>' . $reply['name'] . '</td>

	</tr>
	</table>

    <p align=center>' . hesk_unhortenUrl($reply['message']) . '</p>
  
  <tr>  
 
  </tr> 
    ';
}

///////////////////////////////////////////////////////



// Print "end of ticket" message
//echo '<div style="page-break-after: always;">' . $hesklang['end_ticket'] . "</div>";
  echo '
    <hr />

	<table align=center border="0">
	<tr>
		<td>' . $hesklang[''] . ' ***FABS Network Team Lahore***</td>
	</tr>
	</table>
';